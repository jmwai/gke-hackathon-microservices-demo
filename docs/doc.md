
# Technical Documentation: Online Boutique

## 1. Introduction

This document provides a comprehensive technical overview of the Online Boutique application, a cloud-native microservices demo application. The application is a web-based e-commerce platform where users can browse items, add them to their cart, and make purchases. It is designed to showcase a variety of cloud-native technologies and best practices.

## 2. System Architecture

The Online Boutique application is built upon a microservices architecture, consisting of 11 distinct services that work together. This architecture allows for independent development, deployment, and scaling of each service.

### 2.1. Architecture Diagram

![Architecture of microservices](docs/img/architecture-diagram.png)

### 2.2. Microservice Descriptions

The following table provides a detailed description of each microservice:

| Service | Language | Description |
|---|---|---|
| `frontend` | Go | Exposes an HTTP server to serve the website. It is the entry point for all user interactions and communicates with the backend services via gRPC. |
| `cartservice` | C# | Manages the user's shopping cart. It uses Redis to store the cart data for each user. |
| `productcatalogservice` | Go | Provides the list of products, allows searching for products, and retrieving individual product details. The product data is stored in a JSON file. |
| `currencyservice` | Node.js | Converts monetary values from one currency to another. It uses real-time exchange rates from the European Central Bank. |
| `paymentservice` | Node.js | Processes payments by charging the user's credit card. This is a mock service and does not perform real transactions. |
| `shippingservice` | Go | Calculates shipping costs and provides a tracking ID for shipped orders. This is a mock service. |
| `emailservice` | Python | Sends order confirmation emails to users. This is a mock service. |
| `checkoutservice` | Go | Orchestrates the checkout process. It coordinates the actions of the `cartservice`, `paymentservice`, `shippingservice`, and `emailservice`. |
| `recommendationservice` | Python | Suggests other products to the user based on the items in their cart. |
| `adservice` | Java | Provides contextual advertisements based on the user's browsing behavior. |
| `loadgenerator` | Python/Locust | A load generation service that simulates user traffic to the application for testing and demonstration purposes. |

## 3. Communication Protocol

The microservices communicate with each other using **gRPC**, a high-performance, open-source universal RPC framework. The API contracts for the services are defined in Protocol Buffers (`.proto` files).

### 3.1. Protocol Buffers Definition

The main Protocol Buffers definition file is `protos/demo.proto`. This file defines the services, RPCs, and message structures for the entire application. Below is a summary of the services defined in the `demo.proto` file:

*   **`CartService`**: Manages the user's shopping cart.
*   **`RecommendationService`**: Provides product recommendations.
*   **`ProductCatalogService`**: Manages the product catalog.
*   **`ShippingService`**: Manages shipping and quotes.
*   **`CurrencyService`**: Handles currency conversion.
*   **`PaymentService`**: Processes payments.
*   **`EmailService`**: Sends emails.
*   **`CheckoutService`**: Orchestrates the checkout process.
*   **`AdService`**: Provides advertisements.

## 4. Deployment

The Online Boutique application is designed to be deployed on **Kubernetes**. The project provides several ways to deploy the application, including raw Kubernetes manifests, Kustomize, and Helm.

### 4.1. Skaffold

**Skaffold** is used to automate the build, push, and deployment of the application. The `skaffold.yaml` file at the root of the project defines the build and deployment configurations for each microservice.

### 4.2. Kubernetes Manifests

The `kubernetes-manifests` directory contains the raw Kubernetes manifests for deploying each microservice. These manifests can be applied to a Kubernetes cluster using `kubectl apply -f`.

### 4.3. Kustomize

The `kustomize` directory contains Kustomize configurations for customizing the deployment. This allows for easy modification of the application's configuration for different environments or use cases.

### 4.4. Helm

The `helm-chart` directory contains a Helm chart for deploying the application. Helm is a package manager for Kubernetes that simplifies the deployment and management of applications.

## 5. Infrastructure

The infrastructure required to run the Online Boutique application can be provisioned using **Terraform**. The `terraform` directory contains Terraform configurations for creating the necessary cloud resources, such as a Google Kubernetes Engine (GKE) cluster and other dependencies.

## 6. Development

For local development, you can use **Skaffold** to build and deploy the application to a local Kubernetes cluster (e.g., Minikube or Docker Desktop). The `skaffold dev` command will automatically build and deploy the services, and it will also watch for file changes and redeploy the services as you make changes to the code.

## 7. Testing

The project includes a `loadgenerator` service that is used for load testing the application. This service is built using **Locust**, an open-source load testing tool. The `loadgenerator` simulates user traffic and sends requests to the `frontend` service to test the performance and scalability of the application.
