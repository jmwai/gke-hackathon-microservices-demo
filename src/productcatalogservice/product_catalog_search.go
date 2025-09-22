// Copyright 2024 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
	"context"
	"strings"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/productcatalogservice/genproto"
)

// searchProductsFromCache performs search in the cached catalog
func (p *productCatalog) searchProductsFromCache(ctx context.Context, query string) (*pb.SearchProductsResponse, error) {
	log.Infof("Searching products in cache for query: %s", query)

	var ps []*pb.Product
	for _, product := range p.parseCatalog() {
		if strings.Contains(strings.ToLower(product.Name), strings.ToLower(query)) ||
			strings.Contains(strings.ToLower(product.Description), strings.ToLower(query)) {
			ps = append(ps, product)
		}
	}

	return &pb.SearchProductsResponse{Results: ps}, nil
}

// searchProductsFromDatabase performs search with fresh database data
func (p *productCatalog) searchProductsFromDatabase(ctx context.Context, query string) (*pb.SearchProductsResponse, error) {
	log.Infof("Searching products in database for query: %s", query)

	// Force fresh load from database
	freshCatalog := pb.ListProductsResponse{}
	err := loadCatalog(&freshCatalog)
	if err != nil {
		log.Warnf("Database load failed, falling back to cache: %v", err)
		// Fallback to cache if database fails
		return p.searchProductsFromCache(ctx, query)
	}

	// Search in fresh database results
	var ps []*pb.Product
	for _, product := range freshCatalog.Products {
		if strings.Contains(strings.ToLower(product.Name), strings.ToLower(query)) ||
			strings.Contains(strings.ToLower(product.Description), strings.ToLower(query)) {
			ps = append(ps, product)
		}
	}

	return &pb.SearchProductsResponse{Results: ps}, nil
}
