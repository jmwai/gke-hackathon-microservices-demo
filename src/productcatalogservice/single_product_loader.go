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
	"fmt"
	"net"
	"os"
	"strings"

	"cloud.google.com/go/alloydbconn"
	pb "github.com/GoogleCloudPlatform/microservices-demo/src/productcatalogservice/genproto"
	"github.com/jackc/pgx/v5/pgxpool"
)

// loadSingleProductFromAlloyDB loads a single product by ID from AlloyDB
func loadSingleProductFromAlloyDB(productID string) (*pb.Product, error) {
	log.Infof("loading single product %s from AlloyDB...", productID)

	projectID := os.Getenv("PROJECT_ID")
	region := os.Getenv("REGION")
	pgClusterName := os.Getenv("ALLOYDB_CLUSTER_NAME")
	pgInstanceName := os.Getenv("ALLOYDB_INSTANCE_NAME")
	pgDatabaseName := os.Getenv("ALLOYDB_DATABASE_NAME")
	pgTableName := os.Getenv("ALLOYDB_TABLE_NAME")
	pgSecretName := os.Getenv("ALLOYDB_SECRET_NAME")
	pgPrimaryIP := os.Getenv("ALLOYDB_PRIMARY_IP")

	pgPassword, err := getSecretPayload(projectID, pgSecretName, "latest")
	if err != nil {
		return nil, err
	}

	sslMode := "disable"
	if pgPrimaryIP != "" {
		// Direct private IP connections must use TLS.
		sslMode = "require"
	}

	dsn := fmt.Sprintf(
		"user=%s password=%s dbname=%s sslmode=%s",
		"postgres", pgPassword, pgDatabaseName, sslMode,
	)

	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		log.Warnf("failed to parse DSN config: %v", err)
		return nil, err
	}

	if pgPrimaryIP != "" {
		// Use direct TCP to the private IP
		config.ConnConfig.Host = pgPrimaryIP
		config.ConnConfig.Port = 5432
		log.Infof("connecting to AlloyDB via private IP %s:5432", pgPrimaryIP)
	} else {
		// Fallback to AlloyDB connector
		dialer, err := alloydbconn.NewDialer(context.Background())
		if err != nil {
			log.Warnf("failed to set-up dialer connection: %v", err)
			return nil, err
		}
		cleanup := func() error { return dialer.Close() }
		defer cleanup()

		pgInstanceURI := fmt.Sprintf("projects/%s/locations/%s/clusters/%s/instances/%s", projectID, region, pgClusterName, pgInstanceName)
		config.ConnConfig.DialFunc = func(ctx context.Context, _ string, _ string) (net.Conn, error) {
			return dialer.Dial(ctx, pgInstanceURI)
		}
	}

	pool, err := pgxpool.NewWithConfig(context.Background(), config)
	if err != nil {
		log.Warnf("failed to set-up pgx pool: %v", err)
		return nil, err
	}
	defer pool.Close()

	// Query for the specific product by ID
	query := "SELECT id, name, description, picture, price_usd_currency_code, " +
		"price_usd_units, price_usd_nanos, categories " +
		"FROM " + pgTableName + " " +
		"WHERE id = $1 LIMIT 1"

	row := pool.QueryRow(context.Background(), query, productID)

	product := &pb.Product{}
	product.PriceUsd = &pb.Money{}

	var categories string
	err = row.Scan(&product.Id, &product.Name, &product.Description,
		&product.Picture, &product.PriceUsd.CurrencyCode, &product.PriceUsd.Units,
		&product.PriceUsd.Nanos, &categories)
	if err != nil {
		log.Warnf("failed to scan product %s: %v", productID, err)
		return nil, err
	}

	categories = strings.ToLower(categories)
	product.Categories = strings.Split(categories, ",")

	log.Infof("successfully loaded product %s from AlloyDB", productID)
	return product, nil
}
