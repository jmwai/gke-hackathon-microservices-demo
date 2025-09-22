// Copyright 2018 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"html/template"
	"io"
	"math/rand"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/gorilla/mux"
	"github.com/pkg/errors"
	"github.com/sirupsen/logrus"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/frontend/genproto"
	"github.com/GoogleCloudPlatform/microservices-demo/src/frontend/money"
	"github.com/GoogleCloudPlatform/microservices-demo/src/frontend/validator"
)

type platformDetails struct {
	css      string
	provider string
}

var (
	frontendMessage  = strings.TrimSpace(os.Getenv("FRONTEND_MESSAGE"))
	isCymbalBrand    = "true" == strings.ToLower(os.Getenv("CYMBAL_BRANDING"))
	assistantEnabled = "true" == strings.ToLower(os.Getenv("ENABLE_ASSISTANT"))
	templates        = template.Must(template.New("").
				Funcs(template.FuncMap{
			"renderMoney":        renderMoney,
			"renderCurrencyLogo": renderCurrencyLogo,
		}).ParseGlob("templates/*.html"))
	plat platformDetails
)

var validEnvs = []string{"local", "gcp", "azure", "aws", "onprem", "alibaba"}

func (fe *frontendServer) homeHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.WithField("currency", currentCurrency(r)).Info("home")
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}
	products, err := fe.getProducts(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve products"), http.StatusInternalServerError)
		return
	}
	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}

	type productView struct {
		Item  *pb.Product
		Price *pb.Money
	}
	ps := make([]productView, len(products))
	for i, p := range products {
		price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrapf(err, "failed to do currency conversion for product %s", p.GetId()), http.StatusInternalServerError)
			return
		}
		ps[i] = productView{p, price}
	}

	// Set ENV_PLATFORM (default to local if not set; use env var if set; otherwise detect GCP, which overrides env)_
	var env = os.Getenv("ENV_PLATFORM")
	// Only override from env variable if set + valid env
	if env == "" || stringinSlice(validEnvs, env) == false {
		fmt.Println("env platform is either empty or invalid")
		env = "local"
	}
	// Autodetect GCP
	addrs, err := net.LookupHost("metadata.google.internal.")
	if err == nil && len(addrs) >= 0 {
		log.Debugf("Detected Google metadata server: %v, setting ENV_PLATFORM to GCP.", addrs)
		env = "gcp"
	}

	log.Debugf("ENV_PLATFORM is: %s", env)
	plat = platformDetails{}
	plat.setPlatformDetails(strings.ToLower(env))

	if err := templates.ExecuteTemplate(w, "home", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": true,
		"currencies":    currencies,
		"products":      ps,
		"cart_size":     cartSize(cart),
		"banner_color":  os.Getenv("BANNER_COLOR"), // illustrates canary deployments
		"ad":            fe.chooseAd(r.Context(), []string{}, log),
	})); err != nil {
		log.Error(err)
	}
}

func (fe *frontendServer) searchHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	query := r.URL.Query().Get("q")

	log.WithField("query", query).Info("search page")

	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}

	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}

	type productView struct {
		Item  *pb.Product
		Price *pb.Money
	}

	var ps []productView

	// If there's a query, perform search
	if query != "" {
		// Use database-consistent search for accurate results
		filteredProducts, err := fe.searchProducts(r.Context(), query)
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrap(err, "could not search products"), http.StatusInternalServerError)
			return
		}

		// Convert to productView
		ps = make([]productView, len(filteredProducts))
		for i, p := range filteredProducts {
			price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
			if err != nil {
				renderHTTPError(log, r, w, errors.Wrapf(err, "failed to do currency conversion for product %s", p.GetId()), http.StatusInternalServerError)
				return
			}
			ps[i] = productView{p, price}
		}
	}

	if err := templates.ExecuteTemplate(w, "search", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": true,
		"currencies":    currencies,
		"products":      ps,
		"query":         query,
		"cart_size":     cartSize(cart),
		"banner_color":  os.Getenv("BANNER_COLOR"),
	})); err != nil {
		log.Error(err)
	}
}

func (plat *platformDetails) setPlatformDetails(env string) {
	if env == "aws" {
		plat.provider = "AWS"
		plat.css = "aws-platform"
	} else if env == "onprem" {
		plat.provider = "On-Premises"
		plat.css = "onprem-platform"
	} else if env == "azure" {
		plat.provider = "Azure"
		plat.css = "azure-platform"
	} else if env == "gcp" {
		plat.provider = "Google Cloud"
		plat.css = "gcp-platform"
	} else if env == "alibaba" {
		plat.provider = "Alibaba Cloud"
		plat.css = "alibaba-platform"
	} else {
		plat.provider = "local"
		plat.css = "local"
	}
}

func (fe *frontendServer) productHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	id := mux.Vars(r)["id"]
	if id == "" {
		renderHTTPError(log, r, w, errors.New("product id not specified"), http.StatusBadRequest)
		return
	}
	log.WithField("id", id).WithField("currency", currentCurrency(r)).
		Debug("serving product page")

	p, err := fe.getProduct(r.Context(), id)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve product"), http.StatusInternalServerError)
		return
	}
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}

	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}

	price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to convert currency"), http.StatusInternalServerError)
		return
	}

	// ignores the error retrieving recommendations since it is not critical
	recommendations, err := fe.getRecommendations(r.Context(), sessionID(r), []string{id})
	if err != nil {
		log.WithField("error", err).Warn("failed to get product recommendations")
	}

	product := struct {
		Item  *pb.Product
		Price *pb.Money
	}{p, price}

	// Fetch packaging info (weight/dimensions) of the product
	// The packaging service is an optional microservice you can run as part of a Google Cloud demo.
	var packagingInfo *PackagingInfo = nil
	if isPackagingServiceConfigured() {
		packagingInfo, err = httpGetPackagingInfo(id)
		if err != nil {
			fmt.Println("Failed to obtain product's packaging info:", err)
		}
	}

	if err := templates.ExecuteTemplate(w, "product", injectCommonTemplateData(r, map[string]interface{}{
		"ad":              fe.chooseAd(r.Context(), p.Categories, log),
		"show_currency":   true,
		"currencies":      currencies,
		"product":         product,
		"recommendations": recommendations,
		"cart_size":       cartSize(cart),
		"packagingInfo":   packagingInfo,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) addToCartHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	quantity, _ := strconv.ParseUint(r.FormValue("quantity"), 10, 32)
	productID := r.FormValue("product_id")
	payload := validator.AddToCartPayload{
		Quantity:  quantity,
		ProductID: productID,
	}
	if err := payload.Validate(); err != nil {
		renderHTTPError(log, r, w, validator.ValidationErrorResponse(err), http.StatusUnprocessableEntity)
		return
	}
	log.WithField("product", payload.ProductID).WithField("quantity", payload.Quantity).Debug("adding to cart")

	p, err := fe.getProduct(r.Context(), payload.ProductID)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve product"), http.StatusInternalServerError)
		return
	}

	// Add to cart first (preserve existing behavior)
	if err := fe.insertCart(r.Context(), sessionID(r), p.GetId(), int32(payload.Quantity)); err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to add to cart"), http.StatusInternalServerError)
		return
	}

	// Check if smart add-to-cart features are enabled
	if fe.shouldUseSmartCart() {
		// Trigger agent-based cart analysis in background (don't block user)
		go fe.analyzeCartWithAgent(r.Context(), sessionID(r), p, payload.Quantity)
	}

	w.Header().Set("location", baseUrl+"/cart")
	w.WriteHeader(http.StatusFound)
}

func (fe *frontendServer) shouldUseSmartCart() bool {
	return os.Getenv("SMART_CART_DISABLED") != "true"
}

func (fe *frontendServer) analyzeCartWithAgent(ctx context.Context, sessionId string, product interface{}, quantity uint64) {
	// This runs in background to provide intelligence without blocking the user
	// We'll use this to populate recommendations and insights for the cart page

	// Create a new context with timeout for this background operation
	bgCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	// Get current cart contents
	cart, err := fe.getCart(bgCtx, sessionId)
	if err != nil {
		return // Fail silently for background operation
	}

	// Prepare agent request for cart analysis and ensure ADK session exists
	userId := sessionId
	agentGatewayBaseURL := "http://agents-gateway:80"
	cacheKey := fmt.Sprintf("%s::%s", userId, fe.adkAppName)
	fe.adkSessionsMu.RLock()
	cachedSessionId, ok := fe.adkSessions[cacheKey]
	fe.adkSessionsMu.RUnlock()
	adkSessionId := cachedSessionId
	if !ok || adkSessionId == "" {
		// Create ADK session for this background analysis user/app
		sessionURL := fmt.Sprintf("%s/apps/%s/users/%s/sessions", agentGatewayBaseURL, fe.adkAppName, userId)
		sessionReqBody := map[string]string{
			"appName": fe.adkAppName,
			"userId":  userId,
		}
		sessionJSON, _ := json.Marshal(sessionReqBody)
		client := &http.Client{Timeout: 10 * time.Second}
		if resp, err := client.Post(sessionURL, "application/json", strings.NewReader(string(sessionJSON))); err == nil {
			defer resp.Body.Close()
			var sessionData map[string]interface{}
			if json.NewDecoder(resp.Body).Decode(&sessionData) == nil {
				if id, ok := sessionData["id"].(string); ok && id != "" {
					adkSessionId = id
					fe.adkSessionsMu.Lock()
					fe.adkSessions[cacheKey] = id
					fe.adkSessionsMu.Unlock()
				}
			}
		}
	}
	if adkSessionId == "" {
		adkSessionId = sessionId
	}

	// Build cart context for the agent
	cartItems := make([]map[string]interface{}, len(cart))
	for i, item := range cart {
		cartItems[i] = map[string]interface{}{
			"product_id": item.GetProductId(),
			"quantity":   item.GetQuantity(),
		}
	}

	agentRequest := map[string]interface{}{
		"appName":   fe.adkAppName,
		"userId":    userId,
		"sessionId": adkSessionId,
		"newMessage": map[string]interface{}{
			"role": "user",
			"parts": []map[string]interface{}{
				{
					"text": fmt.Sprintf("Analyze cart and suggest complementary items. Current cart: %v. Just added product with %d quantity.", cartItems, quantity),
				},
			},
		},
	}

	// Call agents-gateway for recommendations
	agentGatewayURL := "http://agents-gateway:80/run"
	requestBody, _ := json.Marshal(agentRequest)

	req, err := http.NewRequest(http.MethodPost, agentGatewayURL, strings.NewReader(string(requestBody)))
	if err != nil {
		return // Fail silently
	}

	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 10 * time.Second}

	resp, err := client.Do(req)
	if err != nil {
		return // Fail silently
	}
	defer resp.Body.Close()

	// Process agent response and potentially cache recommendations
	// This could be stored in Redis or a similar cache for the cart page to use
	// For now, we'll just log it as a proof of concept
	if resp.StatusCode == http.StatusOK {
		fmt.Printf("Background cart analysis completed for session %s\n", sessionId)
	}
}

func (fe *frontendServer) emptyCartHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("emptying cart")

	if err := fe.emptyCart(r.Context(), sessionID(r)); err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to empty cart"), http.StatusInternalServerError)
		return
	}
	w.Header().Set("location", baseUrl+"/")
	w.WriteHeader(http.StatusFound)
}

func (fe *frontendServer) viewCartHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("view user cart")
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}
	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}

	// ignores the error retrieving recommendations since it is not critical
	recommendations, err := fe.getRecommendations(r.Context(), sessionID(r), cartIDs(cart))
	if err != nil {
		log.WithField("error", err).Warn("failed to get product recommendations")
	}

	shippingCost, err := fe.getShippingQuote(r.Context(), cart, currentCurrency(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to get shipping quote"), http.StatusInternalServerError)
		return
	}

	type cartItemView struct {
		Item     *pb.Product
		Quantity int32
		Price    *pb.Money
	}
	items := make([]cartItemView, len(cart))
	totalPrice := pb.Money{CurrencyCode: currentCurrency(r)}
	for i, item := range cart {
		p, err := fe.getProduct(r.Context(), item.GetProductId())
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrapf(err, "could not retrieve product #%s", item.GetProductId()), http.StatusInternalServerError)
			return
		}
		price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrapf(err, "could not convert currency for product #%s", item.GetProductId()), http.StatusInternalServerError)
			return
		}

		multPrice := money.MultiplySlow(*price, uint32(item.GetQuantity()))
		items[i] = cartItemView{
			Item:     p,
			Quantity: item.GetQuantity(),
			Price:    &multPrice}
		totalPrice = money.Must(money.Sum(totalPrice, multPrice))
	}
	totalPrice = money.Must(money.Sum(totalPrice, *shippingCost))
	year := time.Now().Year()

	if err := templates.ExecuteTemplate(w, "cart", injectCommonTemplateData(r, map[string]interface{}{
		"currencies":       currencies,
		"recommendations":  recommendations,
		"cart_size":        cartSize(cart),
		"shipping_cost":    shippingCost,
		"show_currency":    true,
		"total_cost":       totalPrice,
		"items":            items,
		"expiration_years": []int{year, year + 1, year + 2, year + 3, year + 4},
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) placeOrderHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("placing order")

	var (
		email         = r.FormValue("email")
		streetAddress = r.FormValue("street_address")
		zipCode, _    = strconv.ParseInt(r.FormValue("zip_code"), 10, 32)
		city          = r.FormValue("city")
		state         = r.FormValue("state")
		country       = r.FormValue("country")
		ccNumber      = r.FormValue("credit_card_number")
		ccMonth, _    = strconv.ParseInt(r.FormValue("credit_card_expiration_month"), 10, 32)
		ccYear, _     = strconv.ParseInt(r.FormValue("credit_card_expiration_year"), 10, 32)
		ccCVV, _      = strconv.ParseInt(r.FormValue("credit_card_cvv"), 10, 32)
	)

	payload := validator.PlaceOrderPayload{
		Email:         email,
		StreetAddress: streetAddress,
		ZipCode:       zipCode,
		City:          city,
		State:         state,
		Country:       country,
		CcNumber:      ccNumber,
		CcMonth:       ccMonth,
		CcYear:        ccYear,
		CcCVV:         ccCVV,
	}
	if err := payload.Validate(); err != nil {
		renderHTTPError(log, r, w, validator.ValidationErrorResponse(err), http.StatusUnprocessableEntity)
		return
	}

	order, err := pb.NewCheckoutServiceClient(fe.checkoutSvcConn).
		PlaceOrder(r.Context(), &pb.PlaceOrderRequest{
			Email: payload.Email,
			CreditCard: &pb.CreditCardInfo{
				CreditCardNumber:          payload.CcNumber,
				CreditCardExpirationMonth: int32(payload.CcMonth),
				CreditCardExpirationYear:  int32(payload.CcYear),
				CreditCardCvv:             int32(payload.CcCVV)},
			UserId:       sessionID(r),
			UserCurrency: currentCurrency(r),
			Address: &pb.Address{
				StreetAddress: payload.StreetAddress,
				City:          payload.City,
				State:         payload.State,
				ZipCode:       int32(payload.ZipCode),
				Country:       payload.Country},
		})
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to complete the order"), http.StatusInternalServerError)
		return
	}
	log.WithField("order", order.GetOrder().GetOrderId()).Info("order placed")

	order.GetOrder().GetItems()
	recommendations, _ := fe.getRecommendations(r.Context(), sessionID(r), nil)

	totalPaid := *order.GetOrder().GetShippingCost()
	for _, v := range order.GetOrder().GetItems() {
		multPrice := money.MultiplySlow(*v.GetCost(), uint32(v.GetItem().GetQuantity()))
		totalPaid = money.Must(money.Sum(totalPaid, multPrice))
	}

	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}

	if err := templates.ExecuteTemplate(w, "order", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency":   false,
		"currencies":      currencies,
		"order":           order.GetOrder(),
		"total_paid":      &totalPaid,
		"recommendations": recommendations,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) assistantHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}

	if err := templates.ExecuteTemplate(w, "assistant", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": false,
		"currencies":    currencies,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) supportHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}

	if err := templates.ExecuteTemplate(w, "support", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": false,
		"currencies":    currencies,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) logoutHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("logging out")
	for _, c := range r.Cookies() {
		c.Expires = time.Now().Add(-time.Hour * 24 * 365)
		c.MaxAge = -1
		http.SetCookie(w, c)
	}
	w.Header().Set("Location", baseUrl+"/")
	w.WriteHeader(http.StatusFound)
}

func (fe *frontendServer) getProductByID(w http.ResponseWriter, r *http.Request) {
	id := mux.Vars(r)["ids"]
	if id == "" {
		return
	}

	p, err := fe.getProduct(r.Context(), id)
	if err != nil {
		return
	}

	jsonData, err := json.Marshal(p)
	if err != nil {
		fmt.Println(err)
		return
	}

	w.Write(jsonData)
	w.WriteHeader(http.StatusOK)
}

func (fe *frontendServer) chatBotHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	// Determine which system to use based on gradual migration
	sessionId := sessionID(r)
	useNewAgents := fe.shouldUseAgentsGateway(sessionId)

	if useNewAgents {
		fe.handleChatWithAgents(w, r, log)
	} else {
		fe.legacyChatBotHandler(w, r)
	}
}

func (fe *frontendServer) handleChatWithAgents(w http.ResponseWriter, r *http.Request, log logrus.FieldLogger) {
	type ChatRequest struct {
		Message string `json:"message"`
		Image   string `json:"image,omitempty"`
	}

	type ChatResponse struct {
		Message     string                   `json:"message"`
		Products    []map[string]interface{} `json:"products,omitempty"`
		SessionId   string                   `json:"session_id,omitempty"`
		Suggestions []string                 `json:"suggestions,omitempty"`
	}

	// Parse request
	var req ChatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		log.WithField("error", err).Error("failed to decode chat request")
		fe.legacyChatBotHandler(w, r)
		return
	}

	// Prepare agent parts
	parts := []AgentPart{{Text: req.Message}}
	if req.Image != "" && req.Image != "undefined" {
		// Handle base64 image data
		imageData := req.Image
		if strings.Contains(imageData, ",") {
			imageData = strings.Split(imageData, ",")[1]
		}
		// Note: We'd need to decode the base64 here for proper image handling
		parts = append(parts, AgentPart{Text: "Image provided (processing not fully implemented)"})
	}

	// Use the same two-step process as search
	userId := fe.getOrCreateUserId(r)

	// Step 1: Create agent request using same pattern as search
	searchReq := SearchRequest{
		AppName:   fe.adkAppName,
		UserId:    userId,
		SessionId: "", // Will be set after session creation
		NewMessage: map[string]interface{}{
			"role": "user",
			"parts": []map[string]interface{}{
				{"text": req.Message},
			},
		},
	}

	// Add image if provided
	if req.Image != "" && req.Image != "undefined" {
		imageData := req.Image
		if strings.Contains(imageData, ",") {
			imageData = strings.Split(imageData, ",")[1]
		}
		searchReq.NewMessage["parts"] = append(
			searchReq.NewMessage["parts"].([]map[string]interface{}),
			map[string]interface{}{
				"inlineData": map[string]interface{}{
					"data":     imageData,
					"mimeType": "image/jpeg",
				},
			},
		)
	}

	// Step 2: Use the same agents-gateway communication pattern as search
	agentGatewayBaseURL := "http://agents-gateway:80"
	client := &http.Client{Timeout: 30 * time.Second}

	// Reuse ADK session per (userId, appName). Create only if absent.
	cacheKey := fmt.Sprintf("%s::%s", searchReq.UserId, searchReq.AppName)
	fe.adkSessionsMu.RLock()
	cachedSessionId, ok := fe.adkSessions[cacheKey]
	fe.adkSessionsMu.RUnlock()
	if ok && cachedSessionId != "" {
		log.WithFields(logrus.Fields{"user": searchReq.UserId, "app": searchReq.AppName, "session": cachedSessionId}).Info("Reusing ADK session")
		searchReq.SessionId = cachedSessionId
	} else {
		// Create session with state seeded with user_id
		sessionURL := fmt.Sprintf("%s/apps/%s/users/%s/sessions", agentGatewayBaseURL, fe.adkAppName, searchReq.UserId)
		sessionReqBody := map[string]any{
			"state": map[string]any{
				"user_id": userId,
			},
		}
		sessionJSON, _ := json.Marshal(sessionReqBody)

		sessionResp, err := client.Post(sessionURL, "application/json", strings.NewReader(string(sessionJSON)))
		if err != nil {
			log.WithField("error", err).Error("failed to create session with agents-gateway for assistant")
			fe.legacyChatBotHandler(w, r)
			return
		}
		defer sessionResp.Body.Close()

		var sessionData map[string]interface{}
		if err := json.NewDecoder(sessionResp.Body).Decode(&sessionData); err != nil {
			log.WithField("error", err).Error("failed to parse session response for assistant")
			fe.legacyChatBotHandler(w, r)
			return
		}

		// Use and cache the session ID from the agents-gateway response
		if sessionId, ok := sessionData["id"].(string); ok {
			searchReq.SessionId = sessionId
			fe.adkSessionsMu.Lock()
			fe.adkSessions[cacheKey] = sessionId
			fe.adkSessionsMu.Unlock()
			log.WithFields(logrus.Fields{"user": searchReq.UserId, "app": searchReq.AppName, "session": sessionId}).Info("Created and cached ADK session")
		}
	}

	// Now make the actual assistant request (same as search)
	agentGatewayURL := agentGatewayBaseURL + "/run"
	requestJSON, _ := json.Marshal(searchReq)

	log.WithField("request_body", string(requestJSON)).Info("Creating customer service request")
	log.WithField("payload", string(requestJSON)).Info("Forwarding assistant request to agents-gateway")

	agentReq, err := http.NewRequest(http.MethodPost, agentGatewayURL, strings.NewReader(string(requestJSON)))
	if err != nil {
		log.WithField("error", err).Error("failed to create agent request for assistant")
		fe.legacyChatBotHandler(w, r)
		return
	}

	agentReq.Header.Set("Content-Type", "application/json")
	agentReq.Header.Set("Accept", "application/json")

	// Execute the request
	resp, err := client.Do(agentReq)
	if err != nil {
		log.WithField("error", err).Error("assistant agent request failed")
		fe.legacyChatBotHandler(w, r)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.WithField("status", resp.StatusCode).Error("assistant agent returned error")
		fe.legacyChatBotHandler(w, r)
		return
	}

	// Read and parse agent response
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.WithField("error", err).Error("failed to read assistant agent response")
		fe.legacyChatBotHandler(w, r)
		return
	}

	// Log full assistant agent response for observability
	log.WithField("assistant_response_full", string(body)).Info("Assistant agent full response")

	// Log response snippet for debugging
	respSnippet := string(body)
	if len(respSnippet) > 1000 {
		respSnippet = respSnippet[:1000] + "..."
	}
	log.WithField("response_body", respSnippet).Info("Agent response received")

	// Try to decode as object first, then as array if that fails
	var agentResponse map[string]interface{}
	if err := json.NewDecoder(strings.NewReader(string(body))).Decode(&agentResponse); err != nil {
		// If object decode fails, try as array (agents-gateway sometimes returns arrays)
		var arrayResponse []interface{}
		if err2 := json.NewDecoder(strings.NewReader(string(body))).Decode(&arrayResponse); err2 != nil {
			log.WithField("error", err).WithField("body", string(body)).Error("failed to decode assistant agent response as object or array")
			fe.legacyChatBotHandler(w, r)
			return
		}
		// First pass: scan all array elements for functionResponse with products
		if len(arrayResponse) > 0 {
			aggProducts := make([]map[string]interface{}, 0)
			messageBuilder := strings.Builder{}
			for _, elem := range arrayResponse {
				obj, ok := elem.(map[string]interface{})
				if !ok {
					continue
				}
				if content, ok := obj["content"].(map[string]interface{}); ok {
					if parts, ok := content["parts"].([]interface{}); ok {
						for _, p := range parts {
							if partMap, ok := p.(map[string]interface{}); ok {
								if txt, ok := partMap["text"].(string); ok {
									messageBuilder.WriteString(txt)
									messageBuilder.WriteString(" ")
								}
								if funcResp, ok := partMap["functionResponse"].(map[string]interface{}); ok {
									if resp, ok := funcResp["response"]; ok {
										aggProducts = append(aggProducts, fe.extractProductsFromFunctionResponse(resp)...)
									}
								}
							}
						}
					}
				}
			}
			if len(aggProducts) > 0 {
				msg := strings.TrimSpace(messageBuilder.String())
				if msg == "" {
					msg = "I found some products that might interest you!"
				}
				response := ChatResponse{Message: msg, Products: aggProducts, SessionId: userId, Suggestions: []string{}}
				w.Header().Set("Content-Type", "application/json")
				json.NewEncoder(w).Encode(response)
				log.WithField("products_count", len(aggProducts)).Info("Assistant request completed via agents-gateway (from array scan)")
				return
			}

			// Fallback: convert array response to object format for parsing
			// Prefer the LAST element; ADK often appends final state at the end
			last := arrayResponse[len(arrayResponse)-1]
			if objResp, ok := last.(map[string]interface{}); ok {
				agentResponse = objResp
			} else if first, ok := arrayResponse[0].(map[string]interface{}); ok {
				// Fallback to first if last isn't an object
				agentResponse = first
			} else {
				log.WithField("body", string(body)).Error("unexpected array response format from agent")
				fe.legacyChatBotHandler(w, r)
				return
			}
		} else {
			log.Error("empty array response from agent")
			fe.legacyChatBotHandler(w, r)
			return
		}
	}

	// Extract message and products from agent response
	message, products := fe.parseAgentAssistantResponse(agentResponse)

	response := ChatResponse{
		Message:     message,
		Products:    products,
		SessionId:   userId,
		Suggestions: []string{},
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)

	log.WithField("products_count", len(products)).Info("Assistant request completed via agents-gateway")
}

func (fe *frontendServer) shouldUseAgentAssistant() bool {
	// Keep for backward compatibility, but prefer shouldUseAgentsGateway.
	return fe.useAgentsGateway
}

// Agent communication client
func (fe *frontendServer) callAgentsGateway(ctx context.Context, req AgentRequest) (*AgentResponse, error) {
	url := "http://" + fe.agentsGatewaySvcAddr + "/run"

	jsonData, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, err
	}

	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var agentResp AgentResponse
	if err := json.NewDecoder(resp.Body).Decode(&agentResp); err != nil {
		return nil, err
	}

	return &agentResp, nil
}

// Fallback mechanism with gradual migration
func (fe *frontendServer) shouldUseAgentsGateway(sessionID string) bool {
	if !fe.useAgentsGateway {
		return false
	}

	// Implement percentage-based rollout
	if fe.migrationPercent > 0 {
		hash := fnv.New32a()
		hash.Write([]byte(sessionID))
		return int(hash.Sum32()%100) < fe.migrationPercent
	}

	return true
}

// Fallback to legacy services
func (fe *frontendServer) callAgentWithFallback(ctx context.Context, req AgentRequest) (*AgentResponse, error) {
	log := ctx.Value(ctxKeyLog{}).(logrus.FieldLogger)

	// Try agents-gateway first
	resp, err := fe.callAgentsGateway(ctx, req)
	if err != nil {
		// Log the error
		log.WithError(err).Warn("agents-gateway unavailable, falling back to legacy services")

		// Fallback to existing services
		return fe.fallbackToLegacyServices(ctx, req)
	}
	return resp, nil
}

func (fe *frontendServer) fallbackToLegacyServices(ctx context.Context, req AgentRequest) (*AgentResponse, error) {
	// For now, return a basic response indicating fallback
	// This can be enhanced to route to appropriate legacy services
	return &AgentResponse{
		Content: "I'm sorry, our advanced assistant is temporarily unavailable. Please try again later.",
		Error:   "agents-gateway-unavailable",
	}, nil
}

func (fe *frontendServer) enhancedChatBotHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	type ChatRequest struct {
		Message string `json:"message"`
		Image   string `json:"image,omitempty"`
	}

	type ChatResponse struct {
		Message     string                   `json:"message"`
		Products    []map[string]interface{} `json:"products,omitempty"`
		SessionId   string                   `json:"session_id,omitempty"`
		Suggestions []string                 `json:"suggestions,omitempty"`
	}

	// Parse the incoming request
	var chatReq ChatRequest
	if err := json.NewDecoder(r.Body).Decode(&chatReq); err != nil {
		log.WithField("error", err).Error("failed to decode chat request")
		http.Error(w, `{"error": "Invalid request format"}`, http.StatusBadRequest)
		return
	}

	// Generate session ID for the user if not provided.
	sessionId := fe.getOrCreateSessionId(r)
	userId := fe.getOrCreateUserId(r)

	// Ensure ADK session exists and reuse it for Vertex AI sessions.
	agentGatewayBaseURL := "http://agents-gateway:80"
	cacheKey := fmt.Sprintf("%s::%s", userId, fe.reAppName)
	fe.adkSessionsMu.RLock()
	cachedSessionId, ok := fe.adkSessions[cacheKey]
	fe.adkSessionsMu.RUnlock()
	adkSessionId := cachedSessionId
	if !ok || adkSessionId == "" {
		// Create or upsert ADK session using explicit browser sessionId
		sessionURL := fmt.Sprintf("%s/apps/%s/users/%s/sessions/%s", agentGatewayBaseURL, fe.adkAppName, userId, sessionId)
		sessionReqBody := map[string]any{
			"state": map[string]any{
				"user_id": userId,
			},
		}
		sessionJSON, _ := json.Marshal(sessionReqBody)
		client := &http.Client{Timeout: 30 * time.Second}
		req, _ := http.NewRequest(http.MethodPost, sessionURL, strings.NewReader(string(sessionJSON)))
		req.Header.Set("Content-Type", "application/json")
		if _, err := client.Do(req); err == nil {
			adkSessionId = sessionId
			fe.adkSessionsMu.Lock()
			fe.adkSessions[cacheKey] = adkSessionId
			fe.adkSessionsMu.Unlock()
		}
	}
	if adkSessionId == "" {
		// Fall back to cookie session if ADK session creation failed
		adkSessionId = sessionId
	}

	// Prepare agent request based on whether image is provided
	var agentRequest map[string]interface{}

	if chatReq.Image != "" && chatReq.Image != "undefined" {
		// Multimodal request (text + image)
		agentRequest = map[string]interface{}{
			"appName":   fe.adkAppName,
			"userId":    userId,
			"sessionId": adkSessionId,
			"newMessage": map[string]interface{}{
				"role": "user",
				"parts": []map[string]interface{}{
					{"text": chatReq.Message},
					{
						"inlineData": map[string]interface{}{
							"data":     strings.Split(chatReq.Image, ",")[1], // Remove data:image/... prefix
							"mimeType": "image/jpeg",                         // Assume JPEG for now
						},
					},
				},
			},
		}
	} else {
		// Text-only request
		agentRequest = map[string]interface{}{
			"appName":   fe.adkAppName,
			"userId":    userId,
			"sessionId": adkSessionId,
			"newMessage": map[string]interface{}{
				"role": "user",
				"parts": []map[string]interface{}{
					{"text": chatReq.Message},
				},
			},
		}
	}

	// Call agents-gateway
	agentGatewayURL := "http://agents-gateway:80/run"
	requestBody, _ := json.Marshal(agentRequest)

	req, err := http.NewRequest(http.MethodPost, agentGatewayURL, strings.NewReader(string(requestBody)))
	if err != nil {
		log.WithField("error", err).Error("failed to create agent request")
		// Fallback to legacy assistant
		fe.legacyChatBotHandler(w, r)
		return
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.WithField("error", err).Error("agent assistant request failed")
		// Fallback to legacy assistant
		fe.legacyChatBotHandler(w, r)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.WithField("status", resp.StatusCode).Error("agent assistant returned error")
		// Fallback to legacy assistant
		fe.legacyChatBotHandler(w, r)
		return
	}

	// Parse agent response
	var agentResponse map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&agentResponse); err != nil {
		log.WithField("error", err).Error("failed to decode agent response")
		// Fallback to legacy assistant
		fe.legacyChatBotHandler(w, r)
		return
	}

	// Extract message and products from agent response
	message, products := fe.parseAgentAssistantResponse(agentResponse)

	// Prepare response
	response := ChatResponse{
		Message:     message,
		Products:    products,
		SessionId:   sessionId,
		Suggestions: []string{}, // Can be enhanced later
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)

	log.WithField("products_count", len(products)).Info("Enhanced assistant request completed")
}

func (fe *frontendServer) legacyChatBotHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	type Response struct {
		Message string `json:"message"`
	}

	type LLMResponse struct {
		Content string         `json:"content"`
		Details map[string]any `json:"details"`
	}

	var response LLMResponse

	url := "http://" + fe.shoppingAssistantSvcAddr
	req, err := http.NewRequest(http.MethodPost, url, r.Body)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to create request"), http.StatusInternalServerError)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to send request"), http.StatusInternalServerError)
		return
	}

	body, err := io.ReadAll(res.Body)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to read response"), http.StatusInternalServerError)
		return
	}

	fmt.Printf("%+v\n", body)
	fmt.Printf("%+v\n", res)

	err = json.Unmarshal(body, &response)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to unmarshal body"), http.StatusInternalServerError)
		return
	}

	// respond with the same message
	json.NewEncoder(w).Encode(Response{Message: response.Content})

	w.WriteHeader(http.StatusOK)
}

func (fe *frontendServer) getOrCreateSessionId(r *http.Request) string {
	// Prefer cookie first for stability across requests
	if c, err := r.Cookie(cookieSessionID); err == nil && c != nil && c.Value != "" {
		return c.Value
	}
	// Fall back to context-injected ID (middleware)
	if sessionId := sessionID(r); sessionId != "" {
		return sessionId
	}
	// Generate new session ID (last resort)
	return "session_" + strconv.FormatInt(time.Now().UnixNano(), 36) + "_" + fmt.Sprintf("%x", rand.Uint32())
}

func (fe *frontendServer) getOrCreateUserId(r *http.Request) string {
	// For now, use session ID as user ID
	// In a real implementation, this would be tied to user authentication
	sessionId := fe.getOrCreateSessionId(r)
	return sessionId // Return direct session ID to match frontend cart operations
}

func (fe *frontendServer) parseAgentAssistantResponse(agentResponse map[string]interface{}) (string, []map[string]interface{}) {
	message := ""
	var products []map[string]interface{}

	log.WithField("agent_response_keys", getMapKeys(agentResponse)).Info("Parsing agent assistant response")

	// Handle structured output from shopping_assistant_agent
	var shoppingRecs map[string]interface{}
	var found bool

	// First try direct access
	if recs, ok := agentResponse["shopping_recommendations"].(map[string]interface{}); ok {
		shoppingRecs = recs
		found = true
	} else {
		// Try ADK actions.stateDelta structure
		if actions, ok := agentResponse["actions"].(map[string]interface{}); ok {
			if stateDelta, ok := actions["stateDelta"].(map[string]interface{}); ok {
				if recs, ok := stateDelta["shopping_recommendations"].(map[string]interface{}); ok {
					shoppingRecs = recs
					found = true
				}
			}
		}
	}

	if found {
		log.Info("Found 'shopping_recommendations' key, parsing structured output.")
		// Optional action-aware parsing (recommend/cart/order)
		if action, ok := shoppingRecs["action"].(string); ok {
			// Set message from top-level summary if present
			if sum, ok := shoppingRecs["summary"].(string); ok && sum != "" {
				message = sum
			}
			if action == "recommend" {
				if recs, ok := shoppingRecs["recommendations"].([]interface{}); ok {
					for _, rec := range recs {
						if recMap, ok := rec.(map[string]interface{}); ok {
							products = append(products, normalizeProductMap(recMap))
						}
					}
				}
			} else if strings.HasPrefix(action, "cart_") {
				if cart, ok := shoppingRecs["cart"].(map[string]interface{}); ok {
					// Build light-weight product list from cart items if available
					if items, ok := cart["items"].([]interface{}); ok {
						for _, it := range items {
							if itm, ok := it.(map[string]interface{}); ok {
								idVal := itm["product_id"]
								nameVal := itm["name"]
								products = append(products, map[string]interface{}{
									"id":          idVal,
									"name":        nameVal,
									"description": "",
									"picture":     "",
								})
							}
						}
					}
				}
			} else if action == "order_submit" {
				// Show confirmation message; products remain empty
			}
		}
		// Extract recommendation summary as message
		if summary, ok := shoppingRecs["recommendation_summary"].(string); ok {
			message = summary
		}

		// Extract product recommendations
		if recommendations, ok := shoppingRecs["recommendations"].([]interface{}); ok {
			for _, rec := range recommendations {
				if recMap, ok := rec.(map[string]interface{}); ok {
					products = append(products, normalizeProductMap(recMap))
				}
			}
		}
	} else if searchResults, ok := agentResponse["search_results"].(map[string]interface{}); ok {
		// Handle structured output from product_discovery_agent.
		log.Info("Found 'search_results' key, parsing structured output.")
		if summary, ok := searchResults["summary"].(string); ok {
			message = summary
		}
		if productList, ok := searchResults["products"].([]interface{}); ok {
			for _, p := range productList {
				if pMap, ok := p.(map[string]interface{}); ok {
					products = append(products, normalizeProductMap(pMap))
				}
			}
		}
	} else {
		// For agents without output_schema, parse raw ADK response with functionResponse
		// Fallback for older ADK format if the structured output is not found
		log.Info("Did not find 'shopping_recommendations' key, attempting to parse legacy ADK format.")
		if candidates, ok := agentResponse["candidates"].([]interface{}); ok && len(candidates) > 0 {
			for _, cand := range candidates {
				candidate, ok := cand.(map[string]interface{})
				if !ok {
					continue
				}
				if content, ok := candidate["content"].(map[string]interface{}); ok {
					if parts, ok := content["parts"].([]interface{}); ok {
						for _, part := range parts {
							if partMap, ok := part.(map[string]interface{}); ok {
								// Extract text message and parse embedded JSON products
								if text, ok := partMap["text"].(string); ok {
									message += text + " "
									products = append(products, parseProductsFromJSONString(text)...)
								}
								// Extract function responses that might contain products
								if funcResp, ok := partMap["functionResponse"].(map[string]interface{}); ok {
									if response, ok := funcResp["response"]; ok {
										products = append(products, fe.extractProductsFromFunctionResponse(response)...)
									} else if respStr, ok := funcResp["response"].(string); ok {
										products = append(products, parseProductsFromJSONString(respStr)...)
									}
								}
							}
						}
					}
				}
			}
		}

		// Deep fallback: scan any nested structures for product-like maps
		if len(products) == 0 {
			products = append(products, extractProductsFromAny(agentResponse)...)
		}
	}

	// Clean up message
	message = strings.TrimSpace(message)
	if message == "" && len(products) > 0 {
		message = "I found some products that might interest you!"
	}

	return message, products
}

// Helper function to get keys from a map for logging
func getMapKeys(m map[string]interface{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}

func (fe *frontendServer) extractProductsFromFunctionResponse(response interface{}) []map[string]interface{} {
	var products []map[string]interface{}

	// Handle different response formats
	switch resp := response.(type) {
	case []interface{}:
		// Array of products
		for _, item := range resp {
			if product, ok := item.(map[string]interface{}); ok {
				// Ensure required fields exist
				if _, hasId := product["id"]; hasId {
					products = append(products, normalizeProductMap(product))
				}
			}
		}
	case map[string]interface{}:
		// Single product
		if _, hasId := resp["id"]; hasId {
			products = append(products, normalizeProductMap(resp))
		}
	}

	return products
}

// parseProductsFromJSONString tries to parse a JSON string and extract products arrays
func parseProductsFromJSONString(s string) []map[string]interface{} {
	var out []map[string]interface{}
	trim := strings.TrimSpace(s)
	if trim == "" {
		return out
	}
	// Only try to parse likely JSON payloads
	if !(strings.HasPrefix(trim, "{") || strings.HasPrefix(trim, "[")) {
		return out
	}
	var any interface{}
	if err := json.Unmarshal([]byte(trim), &any); err != nil {
		return out
	}
	return extractProductsFromAny(any)
}

// extractProductsFromAny recursively scans for arrays/maps that look like products
func extractProductsFromAny(v interface{}) []map[string]interface{} {
	var collected []map[string]interface{}
	switch val := v.(type) {
	case []interface{}:
		for _, item := range val {
			collected = append(collected, extractProductsFromAny(item)...)
		}
	case map[string]interface{}:
		// If this map looks like a product, add it
		if isProductMap(val) {
			collected = append(collected, normalizeProductMap(val))
		}
		// If it contains a key named "products" with an array, use that
		if arr, ok := val["products"].([]interface{}); ok {
			for _, p := range arr {
				if pm, ok := p.(map[string]interface{}); ok {
					collected = append(collected, normalizeProductMap(pm))
				}
			}
		}
		for _, nested := range val {
			collected = append(collected, extractProductsFromAny(nested)...)
		}
	}
	return collected
}

func isProductMap(m map[string]interface{}) bool {
	_, hasID := m["id"]
	_, hasName := m["name"]
	return hasID && hasName
}

func normalizeProductMap(m map[string]interface{}) map[string]interface{} {
	// Normalize picture field from product_image_url if needed
	picture := m["picture"]
	if picture == nil || picture == "" {
		if piu, ok := m["product_image_url"]; ok {
			picture = piu
		}
	}
	return map[string]interface{}{
		"id":          m["id"],
		"name":        m["name"],
		"description": m["description"],
		"picture":     picture,
	}
}

func (fe *frontendServer) agentSearchHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Set CORS headers for frontend access
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	w.Header().Set("Content-Type", "application/json")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	// Parse the incoming request
	var searchReq SearchRequest
	if err := json.NewDecoder(r.Body).Decode(&searchReq); err != nil {
		log.WithField("error", err).Error("failed to parse search request")
		http.Error(w, `{"error": "Invalid request format"}`, http.StatusBadRequest)
		return
	}

	log.WithField("query", searchReq).Info("Agent search request received")

	// Create session with agents-gateway if needed
	agentGatewayBaseURL := "http://agents-gateway:80"
	client := &http.Client{Timeout: 30 * time.Second}

	// Try to create session first
	sessionURL := fmt.Sprintf("%s/apps/%s/users/%s/sessions", agentGatewayBaseURL, searchReq.AppName, searchReq.UserId)
	sessionReqBody := map[string]string{
		"appName": searchReq.AppName,
		"userId":  searchReq.UserId,
	}
	sessionJSON, _ := json.Marshal(sessionReqBody)

	sessionResp, err := client.Post(sessionURL, "application/json", strings.NewReader(string(sessionJSON)))
	if err != nil {
		log.WithField("error", err).Error("failed to create session with agents-gateway")
		// Fall back to fallback search
		fe.fallbackSearchWrapper(w, r, searchReq)
		return
	}
	defer sessionResp.Body.Close()

	var sessionData map[string]interface{}
	if err := json.NewDecoder(sessionResp.Body).Decode(&sessionData); err != nil {
		log.WithField("error", err).Error("failed to parse session response")
		fe.fallbackSearchWrapper(w, r, searchReq)
		return
	}

	// Use the session ID from the agents-gateway response
	if sessionId, ok := sessionData["id"].(string); ok {
		searchReq.SessionId = sessionId
	}

	// Now make the actual search request
	agentGatewayURL := agentGatewayBaseURL + "/run"
	requestJSON, _ := json.Marshal(searchReq)

	log.WithField("payload", string(requestJSON)).Info("Forwarding search request to agents-gateway")

	req, err := http.NewRequest(http.MethodPost, agentGatewayURL, strings.NewReader(string(requestJSON)))
	if err != nil {
		log.WithField("error", err).Error("failed to create agent request")
		fe.fallbackSearchWrapper(w, r, searchReq)
		return
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	// Execute the request
	resp, err := client.Do(req)
	if err != nil {
		log.WithField("error", err).Error("agent search request failed")
		fe.fallbackSearchWrapper(w, r, searchReq)
		return
	}
	defer resp.Body.Close()

	// Read the response
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.WithField("error", err).Error("failed to read agent response")
		fe.fallbackSearchWrapper(w, r, searchReq)
		return
	}

	// Log full agent response at debug level for observability
	log.WithField("agent_response_full", string(body)).Info("Agent search full response")

	// Log response snippet
	respSnippet := string(body)
	if len(respSnippet) > 512 {
		respSnippet = respSnippet[:512] + "..."
	}
	log.WithFields(logrus.Fields{"status": resp.StatusCode, "response": respSnippet}).Info("Agent search response")

	// Forward the status code and response
	w.WriteHeader(resp.StatusCode)
	w.Write(body)

	log.WithField("status", resp.StatusCode).Info("Agent search request completed")
}

type SearchRequest struct {
	AppName    string                 `json:"appName"`
	UserId     string                 `json:"userId"`
	SessionId  string                 `json:"sessionId"`
	NewMessage map[string]interface{} `json:"newMessage"`
}

func (fe *frontendServer) fallbackSearchWrapper(w http.ResponseWriter, r *http.Request, searchReq SearchRequest) {
	// Extract search query from the agent request and perform fallback search
	if newMessage, ok := searchReq.NewMessage["parts"].([]interface{}); ok {
		if len(newMessage) > 0 {
			if part, ok := newMessage[0].(map[string]interface{}); ok {
				if query, ok := part["text"].(string); ok {
					// Perform fallback search and return results
					products, err := fe.getProducts(r.Context())
					if err != nil {
						http.Error(w, `{"error": "Search temporarily unavailable"}`, http.StatusInternalServerError)
						return
					}

					// Simple text matching
					var matchingProducts []map[string]interface{}
					queryLower := strings.ToLower(query)

					for _, product := range products {
						nameMatch := strings.Contains(strings.ToLower(product.GetName()), queryLower)
						descMatch := strings.Contains(strings.ToLower(product.GetDescription()), queryLower)

						// Check categories
						categoryMatch := false
						for _, category := range product.GetCategories() {
							if strings.Contains(strings.ToLower(category), queryLower) {
								categoryMatch = true
								break
							}
						}

						if nameMatch || descMatch || categoryMatch {
							matchingProducts = append(matchingProducts, map[string]interface{}{
								"id":          product.GetId(),
								"name":        product.GetName(),
								"description": product.GetDescription(),
								"picture":     product.GetPicture(),
								"categories":  product.GetCategories(),
							})
						}

						// Limit results
						if len(matchingProducts) >= 10 {
							break
						}
					}

					response := map[string]interface{}{
						"products": matchingProducts,
						"query":    query,
						"count":    len(matchingProducts),
					}

					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(response)
					return
				}
			}
		}
	}

	// If we can't extract the query, return an error
	http.Error(w, `{"error": "Could not process search request"}`, http.StatusInternalServerError)
}

func (fe *frontendServer) fallbackSearchHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	// Set CORS headers
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")

	query := r.URL.Query().Get("q")
	if query == "" {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"products": []interface{}{},
			"message":  "No search query provided",
		})
		return
	}

	log.WithField("query", query).Info("Performing fallback search")

	// Simple fallback: get all products and filter by name/description
	products, err := fe.getProducts(r.Context())
	if err != nil {
		log.WithField("error", err).Error("failed to get products for fallback search")
		http.Error(w, `{"error": "Search temporarily unavailable"}`, http.StatusInternalServerError)
		return
	}

	// Simple text matching
	var matchingProducts []map[string]interface{}
	queryLower := strings.ToLower(query)

	for _, product := range products {
		nameMatch := strings.Contains(strings.ToLower(product.GetName()), queryLower)
		descMatch := strings.Contains(strings.ToLower(product.GetDescription()), queryLower)

		// Check categories
		categoryMatch := false
		for _, category := range product.GetCategories() {
			if strings.Contains(strings.ToLower(category), queryLower) {
				categoryMatch = true
				break
			}
		}

		if nameMatch || descMatch || categoryMatch {
			matchingProducts = append(matchingProducts, map[string]interface{}{
				"id":          product.GetId(),
				"name":        product.GetName(),
				"description": product.GetDescription(),
				"picture":     product.GetPicture(),
				"categories":  product.GetCategories(),
			})
		}

		// Limit results
		if len(matchingProducts) >= 10 {
			break
		}
	}

	response := map[string]interface{}{
		"products": matchingProducts,
		"query":    query,
		"count":    len(matchingProducts),
	}

	json.NewEncoder(w).Encode(response)
}

func (fe *frontendServer) featureFlagsHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	// Feature flags for smart search and shopping assistant
	flags := map[string]interface{}{
		// Search features
		"agent_search_enabled":       true, // Can be controlled via environment variable
		"search_suggestions_enabled": true,
		"search_analytics_enabled":   false,

		// Shopping assistant features
		"agent_assistant_enabled":      true,
		"hybrid_assistant_mode":        true, // Use both old and new systems
		"assistant_session_continuity": true,
		"assistant_personalization":    true,
		"assistant_multimodal":         true, // Support image + text

		// Recommendation features
		"agent_recommendations_enabled": true,
		"enhanced_product_cards":        true,
		"contextual_suggestions":        true,

		// Cart and checkout features
		"smart_add_to_cart_enabled":    true,
		"cart_recommendations_enabled": true,
		"checkout_assistance_enabled":  true,
		"intelligent_quantity_suggest": true,
		"cart_optimization_enabled":    true,

		// Customer service features
		"customer_service_enabled":      true,
		"ai_order_tracking_enabled":     true,
		"ai_returns_processing_enabled": true,
		"policy_assistance_enabled":     true,
		"support_escalation_enabled":    true,
		"chat_support_enabled":          true,
	}

	// Check environment variables for feature flags
	if os.Getenv("AGENT_SEARCH_DISABLED") == "true" {
		flags["agent_search_enabled"] = false
	}
	if os.Getenv("AGENT_ASSISTANT_DISABLED") == "true" {
		flags["agent_assistant_enabled"] = false
		flags["hybrid_assistant_mode"] = false
	}
	if os.Getenv("ASSISTANT_LEGACY_ONLY") == "true" {
		flags["agent_assistant_enabled"] = false
		flags["hybrid_assistant_mode"] = false
	}
	if os.Getenv("SMART_CART_DISABLED") == "true" {
		flags["smart_add_to_cart_enabled"] = false
		flags["cart_recommendations_enabled"] = false
		flags["intelligent_quantity_suggest"] = false
	}
	if os.Getenv("CHECKOUT_AGENTS_DISABLED") == "true" {
		flags["checkout_assistance_enabled"] = false
		flags["cart_optimization_enabled"] = false
	}
	if os.Getenv("CUSTOMER_SERVICE_DISABLED") == "true" {
		flags["customer_service_enabled"] = false
		flags["ai_order_tracking_enabled"] = false
		flags["ai_returns_processing_enabled"] = false
		flags["policy_assistance_enabled"] = false
		flags["support_escalation_enabled"] = false
		flags["chat_support_enabled"] = false
	}

	json.NewEncoder(w).Encode(flags)
}

func (fe *frontendServer) smartCartRecommendationsHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	if !fe.shouldUseSmartCart() {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"recommendations": []interface{}{},
			"message":         "Smart cart features disabled",
		})
		return
	}

	sessionId := sessionID(r)
	if sessionId == "" {
		http.Error(w, `{"error": "No session found"}`, http.StatusBadRequest)
		return
	}

	// Get current cart
	cart, err := fe.getCart(r.Context(), sessionId)
	if err != nil {
		log.WithField("error", err).Error("failed to get cart for recommendations")
		http.Error(w, `{"error": "Failed to get cart"}`, http.StatusInternalServerError)
		return
	}

	if len(cart) == 0 {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"recommendations": []interface{}{},
			"message":         "Cart is empty",
		})
		return
	}

	// Build cart context for the agent
	cartItems := make([]map[string]interface{}, len(cart))
	for i, item := range cart {
		cartItems[i] = map[string]interface{}{
			"product_id": item.GetProductId(),
			"quantity":   item.GetQuantity(),
		}
	}

	// Prepare agent request
	userId := sessionId
	agentRequest := map[string]interface{}{
		"appName":   fe.reAppName,
		"userId":    userId,
		"sessionId": sessionId,
		"newMessage": map[string]interface{}{
			"role": "user",
			"parts": []map[string]interface{}{
				{
					"text": fmt.Sprintf("Based on my current cart contents %v, suggest 3-5 complementary products that would go well with these items. Focus on accessories, matching items, or things commonly bought together.", cartItems),
				},
			},
		},
	}

	// Call agents-gateway
	agentGatewayURL := "http://agents-gateway:80/run"
	requestBody, _ := json.Marshal(agentRequest)

	req, err := http.NewRequest(http.MethodPost, agentGatewayURL, strings.NewReader(string(requestBody)))
	if err != nil {
		log.WithField("error", err).Error("failed to create agent request")
		http.Error(w, `{"error": "Failed to create recommendation request"}`, http.StatusInternalServerError)
		return
	}

	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 15 * time.Second}

	resp, err := client.Do(req)
	if err != nil {
		log.WithField("error", err).Error("agent recommendation request failed")
		// Return empty recommendations instead of error to maintain UX
		json.NewEncoder(w).Encode(map[string]interface{}{
			"recommendations": []interface{}{},
			"message":         "Recommendations temporarily unavailable",
		})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.WithField("status", resp.StatusCode).Error("agent returned error")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"recommendations": []interface{}{},
			"message":         "Recommendations temporarily unavailable",
		})
		return
	}

	// Parse agent response
	var agentResponse map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&agentResponse); err != nil {
		log.WithField("error", err).Error("failed to decode agent response")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"recommendations": []interface{}{},
			"message":         "Failed to process recommendations",
		})
		return
	}

	// Extract recommendations from agent response
	message, products := fe.parseAgentAssistantResponse(agentResponse)

	response := map[string]interface{}{
		"recommendations": products,
		"message":         message,
		"cart_count":      len(cart),
	}

	json.NewEncoder(w).Encode(response)
	log.WithField("recommendations_count", len(products)).Info("Smart cart recommendations provided")
}

func (fe *frontendServer) checkoutAssistanceHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	if os.Getenv("CHECKOUT_AGENTS_DISABLED") == "true" {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"guidance":    "Checkout assistance is currently disabled",
			"suggestions": []string{},
		})
		return
	}

	sessionId := sessionID(r)
	if sessionId == "" {
		http.Error(w, `{"error": "No session found"}`, http.StatusBadRequest)
		return
	}

	// Get current cart
	cart, err := fe.getCart(r.Context(), sessionId)
	if err != nil {
		log.WithField("error", err).Error("failed to get cart for checkout assistance")
		http.Error(w, `{"error": "Failed to get cart"}`, http.StatusInternalServerError)
		return
	}

	if len(cart) == 0 {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"guidance":    "Your cart is empty. Add some items before checkout!",
			"suggestions": []string{"Browse our products", "Use our AI search"},
		})
		return
	}

	// Build cart context
	cartItems := make([]map[string]interface{}, len(cart))
	totalItems := 0
	for i, item := range cart {
		cartItems[i] = map[string]interface{}{
			"product_id": item.GetProductId(),
			"quantity":   item.GetQuantity(),
		}
		totalItems += int(item.GetQuantity())
	}

	// Prepare agent request for checkout guidance
	userId := sessionId
	agentRequest := map[string]interface{}{
		"appName":   "checkout_agent",
		"userId":    userId,
		"sessionId": sessionId,
		"newMessage": map[string]interface{}{
			"role": "user",
			"parts": []map[string]interface{}{
				{
					"text": fmt.Sprintf("I'm ready to checkout with %d items in my cart: %v. Provide checkout guidance and any optimization suggestions.", totalItems, cartItems),
				},
			},
		},
	}

	// Call agents-gateway
	agentGatewayURL := "http://agents-gateway:80/run"
	requestBody, _ := json.Marshal(agentRequest)

	req, err := http.NewRequest(http.MethodPost, agentGatewayURL, strings.NewReader(string(requestBody)))
	if err != nil {
		log.WithField("error", err).Error("failed to create checkout agent request")
		// Provide fallback guidance
		fe.provideFallbackCheckoutGuidance(w, len(cart), totalItems)
		return
	}

	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 15 * time.Second}

	resp, err := client.Do(req)
	if err != nil {
		log.WithField("error", err).Error("checkout agent request failed")
		fe.provideFallbackCheckoutGuidance(w, len(cart), totalItems)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.WithField("status", resp.StatusCode).Error("checkout agent returned error")
		fe.provideFallbackCheckoutGuidance(w, len(cart), totalItems)
		return
	}

	// Parse agent response
	var agentResponse map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&agentResponse); err != nil {
		log.WithField("error", err).Error("failed to decode checkout agent response")
		fe.provideFallbackCheckoutGuidance(w, len(cart), totalItems)
		return
	}

	// Extract guidance from agent response
	guidance, _ := fe.parseAgentAssistantResponse(agentResponse)

	response := map[string]interface{}{
		"guidance": guidance,
		"suggestions": []string{
			"Review your items before proceeding",
			"Check shipping address carefully",
			"Verify payment information",
		},
		"cart_items":    len(cart),
		"agent_powered": true,
	}

	json.NewEncoder(w).Encode(response)
	log.Info("Checkout assistance provided via agent")
}

func (fe *frontendServer) provideFallbackCheckoutGuidance(w http.ResponseWriter, cartSize, totalItems int) {
	guidance := fmt.Sprintf("You have %d unique items (%d total) ready for checkout. Please review your order details below.", cartSize, totalItems)

	suggestions := []string{
		"Double-check your shipping address",
		"Verify your payment method",
		"Review items and quantities",
	}

	if cartSize >= 5 {
		suggestions = append(suggestions, "Consider if you need all these items")
	}

	response := map[string]interface{}{
		"guidance":      guidance,
		"suggestions":   suggestions,
		"cart_items":    cartSize,
		"agent_powered": false,
	}

	json.NewEncoder(w).Encode(response)
}

func (fe *frontendServer) customerServiceHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	// Check if customer service agents are enabled
	if os.Getenv("CUSTOMER_SERVICE_DISABLED") == "true" {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"response":            "Customer service agents are currently disabled. Please contact support directly.",
			"escalation_required": true,
		})
		return
	}

	type ServiceRequest struct {
		Type    string                 `json:"type"` // "order_tracking", "returns", "policy", "general"
		Message string                 `json:"message"`
		OrderId string                 `json:"order_id,omitempty"`
		Email   string                 `json:"email,omitempty"`
		Context map[string]interface{} `json:"context,omitempty"`
	}

	var request ServiceRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		log.WithField("error", err).Error("failed to decode service request")
		http.Error(w, `{"error": "Invalid request format"}`, http.StatusBadRequest)
		return
	}

	sessionId := fe.getOrCreateSessionId(r)
	userId := fe.getOrCreateUserId(r)

	// Route to appropriate agent based on request type
	var agentName string
	var enhancedMessage string

	switch request.Type {
	case "order_tracking":
		agentName = "customer_service_agent"
		enhancedMessage = fmt.Sprintf("Order tracking request: %s. Order ID: %s, Email: %s", request.Message, request.OrderId, request.Email)
	case "returns":
		agentName = "customer_service_agent"
		enhancedMessage = fmt.Sprintf("Returns request: %s. Order ID: %s, Email: %s", request.Message, request.OrderId, request.Email)
	case "policy":
		agentName = "customer_service_agent"
		enhancedMessage = fmt.Sprintf("Policy question: %s", request.Message)
	default:
		agentName = "customer_service_agent"
		enhancedMessage = request.Message
	}

	// Prepare agent request
	agentRequest := map[string]interface{}{
		"appName":   agentName,
		"userId":    userId,
		"sessionId": sessionId,
		"newMessage": map[string]interface{}{
			"role": "user",
			"parts": []map[string]interface{}{
				{"text": enhancedMessage},
			},
		},
	}

	// Call agents-gateway
	agentGatewayURL := "http://agents-gateway:80/run"
	requestBody, _ := json.Marshal(agentRequest)

	log.WithField("request_body", string(requestBody)).Info("Creating customer service request")

	req, err := http.NewRequest(http.MethodPost, agentGatewayURL, strings.NewReader(string(requestBody)))
	if err != nil {
		log.WithField("error", err).Error("failed to create customer service request")
		fe.provideEscalationResponse(w, request.Type, "Failed to create support request")
		return
	}

	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 30 * time.Second}

	resp, err := client.Do(req)
	if err != nil {
		log.WithField("error", err).Error("customer service agent request failed")
		fe.provideEscalationResponse(w, request.Type, "Customer service temporarily unavailable")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.WithField("status", resp.StatusCode).Error("customer service agent returned error")
		fe.provideEscalationResponse(w, request.Type, "Support system temporarily unavailable")
		return
	}

	// Parse agent response
	var agentResponse map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&agentResponse); err != nil {
		log.WithField("error", err).Error("failed to decode customer service response")
		fe.provideEscalationResponse(w, request.Type, "Failed to process support request")
		return
	}

	// Extract response from agent
	message, _ := fe.parseAgentAssistantResponse(agentResponse)

	// Check if escalation is needed (simple heuristic)
	escalationNeeded := strings.Contains(strings.ToLower(message), "escalate") ||
		strings.Contains(strings.ToLower(message), "human") ||
		strings.Contains(strings.ToLower(message), "complex")

	response := map[string]interface{}{
		"response":            message,
		"type":                request.Type,
		"escalation_required": escalationNeeded,
		"session_id":          sessionId,
		"agent_powered":       true,
	}

	// Add specific fields based on request type
	if request.Type == "order_tracking" && request.OrderId != "" {
		response["order_id"] = request.OrderId
	}

	json.NewEncoder(w).Encode(response)
	log.WithField("request_type", request.Type).Info("Customer service request processed")
}

func (fe *frontendServer) provideEscalationResponse(w http.ResponseWriter, requestType, reason string) {
	var message string
	switch requestType {
	case "order_tracking":
		message = "I'm having trouble accessing order information right now. Please contact our support team with your order number for immediate assistance."
	case "returns":
		message = "I'm unable to process return requests at the moment. Please reach out to our support team for help with your return."
	case "policy":
		message = "I can't access our policy information right now. Please contact support for detailed policy questions."
	default:
		message = "I'm experiencing technical difficulties. Please contact our support team for assistance."
	}

	response := map[string]interface{}{
		"response":            message,
		"type":                requestType,
		"escalation_required": true,
		"agent_powered":       false,
		"reason":              reason,
	}

	json.NewEncoder(w).Encode(response)
}

func (fe *frontendServer) setCurrencyHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	cur := r.FormValue("currency_code")
	payload := validator.SetCurrencyPayload{Currency: cur}
	if err := payload.Validate(); err != nil {
		renderHTTPError(log, r, w, validator.ValidationErrorResponse(err), http.StatusUnprocessableEntity)
		return
	}
	log.WithField("curr.new", payload.Currency).WithField("curr.old", currentCurrency(r)).
		Debug("setting currency")

	if payload.Currency != "" {
		http.SetCookie(w, &http.Cookie{
			Name:   cookieCurrency,
			Value:  payload.Currency,
			MaxAge: cookieMaxAge,
		})
	}
	referer := r.Header.Get("referer")
	if referer == "" {
		referer = baseUrl + "/"
	}
	w.Header().Set("Location", referer)
	w.WriteHeader(http.StatusFound)
}

// ===================== Agent Tool HTTP Endpoints (Option A) =====================

// GET /api/cart?userId=...
func (fe *frontendServer) apiGetCart(w http.ResponseWriter, r *http.Request) {
	userId := r.URL.Query().Get("userId")
	if userId == "" {
		userId = sessionID(r)
	}
	cart, err := fe.getCart(r.Context(), userId)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]any{"error": "cart_fetch_failed"})
		return
	}

	// Enrich cart items with product details
	items := make([]map[string]any, 0, len(cart))
	var totalPrice float64

	for _, it := range cart {
		// Fetch product details for each cart item
		product, err := fe.getProduct(r.Context(), it.GetProductId())
		if err != nil {
			// If product fetch fails, use basic info
			items = append(items, map[string]any{
				"product_id": it.GetProductId(),
				"name":       it.GetProductId(),
				"quantity":   it.GetQuantity(),
				"price":      "",
				"image":      "",
				"line_total": "",
			})
			continue
		}

		// Calculate line total
		unitPrice := float64(product.GetPriceUsd().GetUnits()) + float64(product.GetPriceUsd().GetNanos())/1000000000.0
		lineTotal := unitPrice * float64(it.GetQuantity())
		totalPrice += lineTotal

		items = append(items, map[string]any{
			"product_id": it.GetProductId(),
			"name":       product.GetName(),
			"quantity":   it.GetQuantity(),
			"price":      fmt.Sprintf("%.2f", unitPrice),
			"image":      product.GetPicture(),
			"line_total": fmt.Sprintf("%.2f", lineTotal),
		})
	}

	json.NewEncoder(w).Encode(map[string]any{
		"cart_id":     userId,
		"items":       items,
		"total_price": fmt.Sprintf("%.2f", totalPrice),
	})
}

// POST /api/cart/add {userId, productId, quantity}
func (fe *frontendServer) apiAddToCart(w http.ResponseWriter, r *http.Request) {
	var req struct {
		UserId    string `json:"userId"`
		ProductId string `json:"productId"`
		Quantity  int32  `json:"quantity"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]any{"error": "bad_request"})
		return
	}
	if req.UserId == "" {
		req.UserId = sessionID(r)
	}
	if req.Quantity <= 0 {
		req.Quantity = 1
	}
	if err := fe.insertCart(r.Context(), req.UserId, req.ProductId, req.Quantity); err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(map[string]any{"error": "add_failed"})
		return
	}
	fe.apiGetCart(w, r.WithContext(r.Context()))
}

// POST /api/cart/remove {userId, productId}
func (fe *frontendServer) apiRemoveFromCart(w http.ResponseWriter, r *http.Request) {
	var req struct{ UserId, ProductId string }
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]any{"error": "bad_request"})
		return
	}
	if req.UserId == "" {
		req.UserId = sessionID(r)
	}
	// Simple implementation: empty cart then re-add everything except ProductId (for demo keep as no-op)
	// Real impl would call a RemoveItem RPC.
	json.NewEncoder(w).Encode(map[string]any{"status": "not_implemented"})
}

// POST /api/checkout {userId, userDetails{name,address}, paymentInfo{last4}}
func (fe *frontendServer) apiCheckout(w http.ResponseWriter, r *http.Request) {
	var req struct {
		UserId      string                         `json:"userId"`
		UserDetails struct{ Name, Address string } `json:"userDetails"`
		PaymentInfo struct{ Last4 string }         `json:"paymentInfo"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]any{"error": "bad_request"})
		return
	}
	if req.UserId == "" {
		req.UserId = sessionID(r)
	}
	// For demo, return a synthetic confirmation and clear the user's cart
	resp := map[string]any{
		"order_id":           "ORDER-" + fmt.Sprintf("%x", rand.Uint32()),
		"status":             "success",
		"tracking_id":        fmt.Sprintf("1Z%x", rand.Uint32()),
		"estimated_delivery": time.Now().Add(48 * time.Hour).Format("2006-01-02"),
		"message":            "Your order has been placed successfully!",
	}

	// Best-effort cart clear after successful checkout. Ignore errors for demo.
	_ = fe.emptyCart(r.Context(), req.UserId)

	json.NewEncoder(w).Encode(resp)
}

// chooseAd queries for advertisements available and randomly chooses one, if
// available. It ignores the error retrieving the ad since it is not critical.
func (fe *frontendServer) chooseAd(ctx context.Context, ctxKeys []string, log logrus.FieldLogger) *pb.Ad {
	ads, err := fe.getAd(ctx, ctxKeys)
	if err != nil {
		log.WithField("error", err).Warn("failed to retrieve ads")
		return nil
	}
	return ads[rand.Intn(len(ads))]
}

func renderHTTPError(log logrus.FieldLogger, r *http.Request, w http.ResponseWriter, err error, code int) {
	log.WithField("error", err).Error("request error")
	errMsg := fmt.Sprintf("%+v", err)

	w.WriteHeader(code)

	if templateErr := templates.ExecuteTemplate(w, "error", injectCommonTemplateData(r, map[string]interface{}{
		"error":       errMsg,
		"status_code": code,
		"status":      http.StatusText(code),
	})); templateErr != nil {
		log.Println(templateErr)
	}
}

func injectCommonTemplateData(r *http.Request, payload map[string]interface{}) map[string]interface{} {
	data := map[string]interface{}{
		"session_id":        sessionID(r),
		"request_id":        r.Context().Value(ctxKeyRequestID{}),
		"user_currency":     currentCurrency(r),
		"platform_css":      plat.css,
		"platform_name":     plat.provider,
		"is_cymbal_brand":   isCymbalBrand,
		"assistant_enabled": assistantEnabled,
		"deploymentDetails": deploymentDetailsMap,
		"frontendMessage":   frontendMessage,
		"currentYear":       time.Now().Year(),
		"baseUrl":           baseUrl,
	}

	for k, v := range payload {
		data[k] = v
	}

	return data
}

func currentCurrency(r *http.Request) string {
	c, _ := r.Cookie(cookieCurrency)
	if c != nil {
		return c.Value
	}
	return defaultCurrency
}

func sessionID(r *http.Request) string {
	v := r.Context().Value(ctxKeySessionID{})
	if v != nil {
		return v.(string)
	}
	return ""
}

func cartIDs(c []*pb.CartItem) []string {
	out := make([]string, len(c))
	for i, v := range c {
		out[i] = v.GetProductId()
	}
	return out
}

// get total # of items in cart
func cartSize(c []*pb.CartItem) int {
	cartSize := 0
	for _, item := range c {
		cartSize += int(item.GetQuantity())
	}
	return cartSize
}

func renderMoney(money pb.Money) string {
	currencyLogo := renderCurrencyLogo(money.GetCurrencyCode())
	return fmt.Sprintf("%s%d.%02d", currencyLogo, money.GetUnits(), money.GetNanos()/10000000)
}

func renderCurrencyLogo(currencyCode string) string {
	logos := map[string]string{
		"USD": "$",
		"CAD": "$",
		"JPY": "¥",
		"EUR": "€",
		"TRY": "₺",
		"GBP": "£",
	}

	logo := "$" //default
	if val, ok := logos[currencyCode]; ok {
		logo = val
	}
	return logo
}

func stringinSlice(slice []string, val string) bool {
	for _, item := range slice {
		if item == val {
			return true
		}
	}
	return false
}
