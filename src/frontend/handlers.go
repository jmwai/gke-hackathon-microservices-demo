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
	"context"
	"encoding/json"
	"fmt"
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

	// Prepare agent request for cart analysis
	userId := "user_" + sessionId

	// Build cart context for the agent
	cartItems := make([]map[string]interface{}, len(cart))
	for i, item := range cart {
		cartItems[i] = map[string]interface{}{
			"product_id": item.GetProductId(),
			"quantity":   item.GetQuantity(),
		}
	}

	agentRequest := map[string]interface{}{
		"appName":   "shopping_assistant_agent",
		"userId":    userId,
		"sessionId": sessionId,
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

	// Check if we should use the enhanced agent-based assistant
	if fe.shouldUseAgentAssistant() {
		fe.enhancedChatBotHandler(w, r)
		return
	}

	// Fallback to legacy shopping assistant
	fe.legacyChatBotHandler(w, r)
}

func (fe *frontendServer) shouldUseAgentAssistant() bool {
	// Check environment variable
	if os.Getenv("AGENT_ASSISTANT_DISABLED") == "true" {
		return false
	}
	if os.Getenv("ASSISTANT_LEGACY_ONLY") == "true" {
		return false
	}

	// Default to agent assistant enabled
	return true
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

	// Generate session ID for the user if not provided
	sessionId := fe.getOrCreateSessionId(r)
	userId := fe.getOrCreateUserId(r)

	// Prepare agent request based on whether image is provided
	var agentRequest map[string]interface{}

	if chatReq.Image != "" && chatReq.Image != "undefined" {
		// Multimodal request (text + image)
		agentRequest = map[string]interface{}{
			"appName":   "shopping_assistant_agent",
			"userId":    userId,
			"sessionId": sessionId,
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
			"appName":   "shopping_assistant_agent",
			"userId":    userId,
			"sessionId": sessionId,
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
	// Try to get session ID from existing session
	if sessionId := sessionID(r); sessionId != "" {
		return sessionId
	}

	// Generate new session ID
	return "session_" + strconv.FormatInt(time.Now().UnixNano(), 36) + "_" +
		fmt.Sprintf("%x", rand.Uint32())
}

func (fe *frontendServer) getOrCreateUserId(r *http.Request) string {
	// For now, use session ID as user ID
	// In a real implementation, this would be tied to user authentication
	sessionId := fe.getOrCreateSessionId(r)
	return "user_" + sessionId
}

func (fe *frontendServer) parseAgentAssistantResponse(agentResponse map[string]interface{}) (string, []map[string]interface{}) {
	message := ""
	var products []map[string]interface{}

	// Parse agent response to extract message and product recommendations
	if candidates, ok := agentResponse["candidates"].([]interface{}); ok && len(candidates) > 0 {
		if candidate, ok := candidates[0].(map[string]interface{}); ok {
			if content, ok := candidate["content"].(map[string]interface{}); ok {
				if parts, ok := content["parts"].([]interface{}); ok {
					for _, part := range parts {
						if partMap, ok := part.(map[string]interface{}); ok {
							// Extract text message
							if text, ok := partMap["text"].(string); ok {
								message += text + " "
							}

							// Extract function responses that might contain products
							if funcResp, ok := partMap["functionResponse"].(map[string]interface{}); ok {
								if funcName, ok := funcResp["name"].(string); ok {
									if funcName == "text_vector_search" || funcName == "get_recommendations" {
										if response, ok := funcResp["response"]; ok {
											products = append(products, fe.extractProductsFromFunctionResponse(response)...)
										}
									}
								}
							}
						}
					}
				}
			}
		}
	}

	// Clean up message
	message = strings.TrimSpace(message)
	if message == "" {
		message = "I found some products that might interest you!"
	}

	return message, products
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
				if id, hasId := product["id"]; hasId {
					productMap := map[string]interface{}{
						"id":          id,
						"name":        product["name"],
						"description": product["description"],
						"picture":     product["picture"],
					}
					products = append(products, productMap)
				}
			}
		}
	case map[string]interface{}:
		// Single product
		if id, hasId := resp["id"]; hasId {
			productMap := map[string]interface{}{
				"id":          id,
				"name":        resp["name"],
				"description": resp["description"],
				"picture":     resp["picture"],
			}
			products = append(products, productMap)
		}
	}

	return products
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

	// Forward the request to agents-gateway
	agentGatewayURL := "http://agents-gateway:80/run"

	// Create a new request to the agents-gateway
	req, err := http.NewRequest(http.MethodPost, agentGatewayURL, r.Body)
	if err != nil {
		log.WithField("error", err).Error("failed to create agent request")
		http.Error(w, `{"error": "Failed to create search request"}`, http.StatusInternalServerError)
		return
	}

	// Copy headers
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	// Set timeout for agent requests
	client := &http.Client{
		Timeout: 30 * time.Second,
	}

	log.Info("Forwarding search request to agents-gateway")

	// Execute the request
	resp, err := client.Do(req)
	if err != nil {
		log.WithField("error", err).Error("agent search request failed")
		http.Error(w, `{"error": "Agent search temporarily unavailable"}`, http.StatusServiceUnavailable)
		return
	}
	defer resp.Body.Close()

	// Read the response
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.WithField("error", err).Error("failed to read agent response")
		http.Error(w, `{"error": "Failed to read agent response"}`, http.StatusInternalServerError)
		return
	}

	// Forward the status code and response
	w.WriteHeader(resp.StatusCode)
	w.Write(body)

	log.WithField("status", resp.StatusCode).Info("Agent search request completed")
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
	userId := "user_" + sessionId
	agentRequest := map[string]interface{}{
		"appName":   "shopping_assistant_agent",
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
	userId := "user_" + sessionId
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
