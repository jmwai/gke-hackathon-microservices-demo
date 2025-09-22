/**
 * Agent Response Parser
 * Handles parsing of structured responses from all agent types
 */

class AgentResponseParser {
    constructor() {
        this.supportedAgents = [
            'product_discovery_agent',
            'shopping_assistant_agent', 
            'customer_service_agent',
            'image_search_agent',
            'checkout_agent',
            'returns_workflow_agent'
        ];
    }

    /**
     * Parse agent response based on agent type and output format
     * @param {Object} agentData - Raw agent response
     * @param {string} agentType - Type of agent that generated the response
     * @returns {Object} Parsed response with standardized format
     */
    parseResponse(agentData, agentType = 'unknown') {
        console.log(`Parsing ${agentType} response:`, agentData);
        
        try {
            // Product Discovery Agent
            if (agentData.search_results) {
                // Prefer richer functionResponse products if present and larger
                const fallback = this.parseFallbackFormat(agentData);
                if (fallback && Array.isArray(fallback.products) && fallback.products.length > (agentData.search_results.products?.length || 0)) {
                    return fallback;
                }
                return this.parseProductDiscovery(agentData.search_results);
            }
            
            // Shopping Assistant Agent
            if (agentData.shopping_recommendations) {
                return this.parseShoppingAssistant(agentData.shopping_recommendations);
            }
            
            // Customer Service Agent
            if (agentData.customer_service_response) {
                return this.parseCustomerService(agentData.customer_service_response);
            }
            
            // Image Search Agent
            if (agentData.image_search_results) {
                return this.parseImageSearch(agentData.image_search_results);
            }
            
            // Checkout Agent
            if (agentData.cart_confirmation_result || agentData.order_submission_result) {
                return this.parseCheckout(agentData);
            }
            
            // Returns Workflow Agents
            if (agentData.verification_result || agentData.eligibility_result || agentData.rma_result) {
                return this.parseReturnsWorkflow(agentData);
            }
            
            // Fallback: Try to parse array format or embedded JSON
            return this.parseFallbackFormat(agentData);
            
        } catch (error) {
            console.error('Error parsing agent response:', error);
            return { type: 'error', message: 'Failed to parse agent response', data: null };
        }
    }

    parseProductDiscovery(searchResults) {
        const products = searchResults.products || [];
        return {
            type: 'product_search',
            products: products.map(item => ({
                id: item.id || 'unknown',
                name: item.name || 'Unknown Product',
                description: item.description || '',
                picture: item.picture || '/static/img/products/placeholder.jpg',
                distance: item.distance || 0
            })),
            summary: searchResults.summary || `Found ${products.length} products`,
            totalResults: products.length
        };
    }

    parseShoppingAssistant(recommendations) {
        const products = recommendations.recommendations || [];
        return {
            type: 'recommendations',
            products: products.map(item => ({
                id: item.id || 'unknown',
                name: item.name || 'Unknown Product',
                description: item.why || item.description || '',
                picture: item.picture || '/static/img/products/placeholder.jpg',
                reason: item.why || '',
                priceRange: item.price_range || ''
            })),
            summary: recommendations.recommendation_summary || `${products.length} recommendations`,
            userContext: recommendations.user_context || {},
            totalResults: recommendations.total_recommendations || products.length
        };
    }

    parseCustomerService(serviceResponse) {
        const result = serviceResponse.support_result || {};
        return {
            type: 'customer_service',
            inquiryType: result.inquiry_type || 'general',
            resolutionStatus: result.resolution_status || 'pending',
            message: result.message || 'No response available',
            orderInfo: result.order_info || null,
            shippingInfo: result.shipping_info || null,
            policyInfo: result.policy_info || null,
            returnInfo: result.return_info || null,
            nextSteps: result.next_steps || [],
            success: serviceResponse.success || false,
            timestamp: serviceResponse.timestamp || new Date().toISOString()
        };
    }

    parseImageSearch(imageResults) {
        const products = imageResults.products || [];
        return {
            type: 'image_search',
            products: products.map(item => ({
                id: item.id || 'unknown',
                name: item.name || 'Unknown Product',
                description: item.description || `Visual similarity: ${((1 - (item.distance || 0)) * 100).toFixed(1)}%`,
                picture: item.picture || '/static/img/products/placeholder.jpg',
                similarityScore: item.similarity_score || (1 - (item.distance || 0)),
                distance: item.distance || 0
            })),
            summary: imageResults.search_summary || `Found ${products.length} visually similar products`,
            totalResults: imageResults.total_results || products.length
        };
    }

    parseCheckout(checkoutData) {
        if (checkoutData.cart_confirmation_result) {
            const result = checkoutData.cart_confirmation_result.checkout_result || {};
            return {
                type: 'cart_confirmation',
                step: result.step || 'cart_confirmation',
                cartDetails: result.cart_details || null,
                requiresUserInput: result.requires_user_input || false,
                nextStep: result.next_step || null,
                success: checkoutData.cart_confirmation_result.success || false
            };
        }
        
        if (checkoutData.order_submission_result) {
            const result = checkoutData.order_submission_result.checkout_result || {};
            return {
                type: 'order_confirmation',
                step: result.step || 'order_submission',
                orderConfirmation: result.order_confirmation || null,
                success: checkoutData.order_submission_result.success || false,
                readyToProceed: checkoutData.order_submission_result.ready_to_proceed || false
            };
        }
        
        return { type: 'checkout_error', message: 'Unknown checkout format' };
    }

    parseReturnsWorkflow(workflowData) {
        if (workflowData.verification_result) {
            const result = workflowData.verification_result.result || {};
            return {
                type: 'purchase_verification',
                orderFound: result.order_found || false,
                orderDetails: result.order_details || null,
                verificationStatus: result.verification_status || 'pending',
                nextStep: result.next_step || null,
                success: workflowData.verification_result.success || false
            };
        }
        
        if (workflowData.eligibility_result) {
            const result = workflowData.eligibility_result.result || {};
            return {
                type: 'return_eligibility',
                eligible: result.eligible || false,
                reason: result.reason || 'No reason provided',
                policyDetails: result.policy_details || null,
                success: workflowData.eligibility_result.success || false
            };
        }
        
        if (workflowData.rma_result) {
            const result = workflowData.rma_result.result || {};
            return {
                type: 'rma_generation',
                rmaNumber: result.rma_number || null,
                shippingLabelUrl: result.shipping_label_url || null,
                instructions: result.instructions || [],
                status: result.status || 'pending',
                success: workflowData.rma_result.success || false
            };
        }
        
        return { type: 'workflow_error', message: 'Unknown workflow format' };
    }

    parseFallbackFormat(agentData) {
        // Handle array format (legacy)
        if (Array.isArray(agentData)) {
            for (const item of agentData) {
                if (item.content && item.content.parts) {
                    for (const part of item.content.parts) {
                        // Function response with products
                        if (part.functionResponse && part.functionResponse.response && Array.isArray(part.functionResponse.response)) {
                            const resp = part.functionResponse.response;
                            return {
                                type: 'function_response',
                                products: resp.map(p => ({
                                    id: p.id || 'unknown',
                                    name: p.name || 'Unknown Product',
                                    description: p.description || '',
                                    picture: p.picture || p.product_image_url || '/static/img/products/placeholder.jpg',
                                    distance: typeof p.distance === 'number' ? p.distance : 0
                                })),
                                summary: `Found ${resp.length} products`,
                                totalResults: resp.length
                            };
                        }
                        if (part.text && (part.text.includes('"products"') || part.text.includes('[{'))) {
                            try {
                                if (part.text.startsWith('{') && part.text.endsWith('}')) {
                                    const parsed = JSON.parse(part.text);
                                    if (parsed.products && Array.isArray(parsed.products)) {
                                        return {
                                            type: 'legacy_search',
                                            products: parsed.products.map(item => ({
                                                id: item.id || 'unknown',
                                                name: item.name || 'Unknown Product',
                                                description: item.description || '',
                                                picture: item.picture || item.product_image_url || '/static/img/products/placeholder.jpg'
                                            })),
                                            summary: parsed.summary || `Found ${parsed.products.length} products`,
                                            totalResults: parsed.products.length
                                        };
                                    }
                                }
                            } catch (e) {
                                console.warn('Failed to parse embedded JSON:', e);
                            }
                        }
                    }
                }
            }
        }
        
        // Handle candidates with functionResponse
        if (agentData.candidates && agentData.candidates.length > 0) {
            for (const cand of agentData.candidates) {
                const parts = (cand.content && cand.content.parts) || [];
                for (const part of parts) {
                    if (part.functionResponse && part.functionResponse.response && Array.isArray(part.functionResponse.response)) {
                        const resp = part.functionResponse.response;
                        return {
                            type: 'function_response',
                            products: resp.map(p => ({
                                id: p.id || 'unknown',
                                name: p.name || 'Unknown Product',
                                description: p.description || '',
                                picture: p.picture || p.product_image_url || '/static/img/products/placeholder.jpg',
                                distance: typeof p.distance === 'number' ? p.distance : 0
                            })),
                            summary: `Found ${resp.length} products`,
                            totalResults: resp.length
                        };
                    }
                }
            }
        }

        // Handle direct product array
        if (Array.isArray(agentData) && agentData.length > 0 && agentData[0].id) {
            return {
                type: 'direct_products',
                products: agentData.map(item => ({
                    id: item.id || 'unknown',
                    name: item.name || 'Unknown Product',
                    description: item.description || '',
                    picture: item.picture || item.product_image_url || '/static/img/products/placeholder.jpg'
                })),
                summary: `Found ${agentData.length} products`,
                totalResults: agentData.length
            };
        }
        
        return { type: 'unknown', message: 'Unable to parse agent response', data: agentData };
    }

    /**
     * Extract products from any response type that contains product data
     * @param {Object} parsedResponse - Response from parseResponse()
     * @returns {Array} Array of product objects or empty array
     */
    extractProducts(parsedResponse) {
        if (parsedResponse.products && Array.isArray(parsedResponse.products)) {
            return parsedResponse.products;
        }
        return [];
    }

    /**
     * Check if response contains product data
     * @param {Object} parsedResponse - Response from parseResponse()
     * @returns {boolean} True if response contains products
     */
    hasProducts(parsedResponse) {
        return this.extractProducts(parsedResponse).length > 0;
    }
}

// Export for use in other files
window.AgentResponseParser = AgentResponseParser;
