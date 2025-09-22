// Copyright 2023 Google LLC
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
	"os"
	"time"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/productcatalogservice/genproto"
	"google.golang.org/grpc/codes"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type productCatalog struct {
	pb.UnimplementedProductCatalogServiceServer
	catalog pb.ListProductsResponse
}

func (p *productCatalog) Check(ctx context.Context, req *healthpb.HealthCheckRequest) (*healthpb.HealthCheckResponse, error) {
	return &healthpb.HealthCheckResponse{Status: healthpb.HealthCheckResponse_SERVING}, nil
}

func (p *productCatalog) Watch(req *healthpb.HealthCheckRequest, ws healthpb.Health_WatchServer) error {
	return status.Errorf(codes.Unimplemented, "health check via Watch not implemented")
}

func (p *productCatalog) ListProducts(ctx context.Context, req *pb.Empty) (*pb.ListProductsResponse, error) {
	time.Sleep(extraLatency)

	if shouldUseDatabase(ctx) {
		return p.getProductsFromDatabase(ctx)
	}
	return p.getProductsFromCache(ctx)
}

func (p *productCatalog) GetProduct(ctx context.Context, req *pb.GetProductRequest) (*pb.Product, error) {
	time.Sleep(extraLatency)

	if shouldUseDatabase(ctx) {
		return p.getProductFromDatabase(ctx, req.Id)
	}
	return p.getProductFromCache(ctx, req.Id)
}

func (p *productCatalog) SearchProducts(ctx context.Context, req *pb.SearchProductsRequest) (*pb.SearchProductsResponse, error) {
	time.Sleep(extraLatency)

	if shouldUseDatabase(ctx) {
		return p.searchProductsFromDatabase(ctx, req.Query)
	}
	return p.searchProductsFromCache(ctx, req.Query)
}

func (p *productCatalog) parseCatalog() []*pb.Product {
	if reloadCatalog || len(p.catalog.Products) == 0 {
		err := loadCatalog(&p.catalog)
		if err != nil {
			return []*pb.Product{}
		}
	}

	return p.catalog.Products
}

// shouldUseDatabase checks request headers to determine data source routing
func shouldUseDatabase(ctx context.Context) bool {
	// Feature flag: only enable selective routing if explicitly configured
	if os.Getenv("ENABLE_SELECTIVE_ROUTING") != "true" {
		// Default behavior: use existing logic (AlloyDB if configured, else local file)
		return os.Getenv("ALLOYDB_CLUSTER_NAME") != ""
	}

	// Check for gRPC metadata requesting database access
	if md, ok := metadata.FromIncomingContext(ctx); ok {
		if values := md.Get("use-database"); len(values) > 0 && values[0] == "true" {
			log.Info("Request header indicates database access required")
			return true
		}
	}

	// Default to cache for performance when selective routing is enabled
	log.Info("Using cache for fast response")
	return false
}

// getProductsFromCache returns products from the cached catalog
func (p *productCatalog) getProductsFromCache(ctx context.Context) (*pb.ListProductsResponse, error) {
	log.Info("Loading products from cache")
	return &pb.ListProductsResponse{Products: p.parseCatalog()}, nil
}

// getProductsFromDatabase forces a fresh load from AlloyDB
func (p *productCatalog) getProductsFromDatabase(ctx context.Context) (*pb.ListProductsResponse, error) {
	log.Info("Loading products from database (forced reload)")

	// Create a fresh catalog response to force database reload
	freshCatalog := pb.ListProductsResponse{}
	err := loadCatalog(&freshCatalog)
	if err != nil {
		log.Warnf("Database load failed, falling back to cache: %v", err)
		// Fallback to cache if database fails
		return p.getProductsFromCache(ctx)
	}

	return &pb.ListProductsResponse{Products: freshCatalog.Products}, nil
}

// getProductFromCache finds a product by ID in the cached catalog
func (p *productCatalog) getProductFromCache(ctx context.Context, productID string) (*pb.Product, error) {
	log.Infof("Looking up product %s from cache", productID)

	var found *pb.Product
	for i := 0; i < len(p.parseCatalog()); i++ {
		if productID == p.parseCatalog()[i].Id {
			found = p.parseCatalog()[i]
			break
		}
	}

	if found == nil {
		return nil, status.Errorf(codes.NotFound, "no product with ID %s", productID)
	}
	return found, nil
}

// getProductFromDatabase finds a product by ID with a fresh database lookup
func (p *productCatalog) getProductFromDatabase(ctx context.Context, productID string) (*pb.Product, error) {
	log.Infof("Looking up product %s from database (direct query)", productID)

	// Check if AlloyDB is configured
	if os.Getenv("ALLOYDB_CLUSTER_NAME") == "" {
		log.Info("AlloyDB not configured, falling back to cache")
		return p.getProductFromCache(ctx, productID)
	}

	// Direct database lookup for single product
	product, err := loadSingleProductFromAlloyDB(productID)
	if err != nil {
		log.Warnf("Database lookup failed for product %s: %v, falling back to cache", productID, err)
		// Fallback to cache if database fails
		return p.getProductFromCache(ctx, productID)
	}

	return product, nil
}
