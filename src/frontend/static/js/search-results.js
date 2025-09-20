/**
 * Search Results Page functionality
 * Handles AI-powered search on the dedicated search results page
 */

class SearchResults {
    constructor() {
        this.agentEndpoint = '/api/agent-search';
        this.fallbackEndpoint = '/api/search';
        this.isAgentSearchEnabled = true;
        
        this.initializeElements();
        this.bindEvents();
        this.loadFeatureFlags();
        
        // Perform search if there's a query in the URL
        this.performInitialSearch();
    }

    initializeElements() {
        this.searchInput = document.getElementById('smart-search-input');
        this.loadingIndicator = document.getElementById('search-loading');
        this.resultsContainer = document.querySelector('.search-results-row');
        this.headerContainer = document.querySelector('.search-results-header');
        
        console.log('Search input found:', !!this.searchInput);
        console.log('Loading indicator found:', !!this.loadingIndicator);
        console.log('Results container found:', !!this.resultsContainer);
        console.log('Header container found:', !!this.headerContainer);
        
        // If results container not found, try alternative selectors
        if (!this.resultsContainer) {
            this.resultsContainer = document.querySelector('.hot-products-row');
            console.log('Alternative results container found:', !!this.resultsContainer);
        }
        
        if (!this.resultsContainer) {
            this.resultsContainer = document.querySelector('.row.px-xl-6');
            console.log('Generic row container found:', !!this.resultsContainer);
        }
        
        // If still not found, create one dynamically
        if (!this.resultsContainer) {
            console.log('Creating results container dynamically');
            const container = document.querySelector('.container-fluid .row .col-12');
            if (container) {
                const resultsRow = document.createElement('div');
                resultsRow.className = 'row search-results-row px-xl-6';
                resultsRow.style.cssText = 'row-gap: 2rem; margin-top: 2rem;';
                container.appendChild(resultsRow);
                this.resultsContainer = resultsRow;
                console.log('Dynamic results container created:', !!this.resultsContainer);
            }
        }
    }

    bindEvents() {
        // Enter key in search input
        if (this.searchInput) {
            this.searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.performNewSearch();
                }
            });
        }
    }

    async loadFeatureFlags() {
        try {
            const response = await fetch('/api/feature-flags');
            if (response.ok) {
                const flags = await response.json();
                this.isAgentSearchEnabled = flags.agent_search_enabled !== false;
            }
        } catch (error) {
            console.log('Feature flags not available, using defaults');
        }
    }

    getQueryFromURL() {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get('q') || '';
    }

    performInitialSearch() {
        const query = this.getQueryFromURL();
        const imageData = sessionStorage.getItem('search_image_data');
        const imageType = sessionStorage.getItem('search_image_type');
        if (imageData && imageType && this.isAgentSearchEnabled) {
            // Image-only agent search
            this.performAgentImageSearch(imageData, imageType);
        } else if (query && this.isAgentSearchEnabled) {
            // If we have a query and agent search is enabled, perform AI search
            this.performAgentSearch(query);
        }
    }

    performNewSearch() {
        const query = this.searchInput.value.trim();
        if (query) {
            // Update URL and perform search
            const newUrl = `/search?q=${encodeURIComponent(query)}`;
            window.history.pushState({}, '', newUrl);
            
            if (this.isAgentSearchEnabled) {
                this.performAgentSearch(query);
            } else {
                // Fallback: reload page with new query
                window.location.reload();
            }
        }
    }

    async performAgentSearch(query) {
        this.showLoading(true);
        this.updateHeader(query, null, true);
        
        // Hide the results container during loading
        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'none';
        }

        try {
            // Generate a session ID for the user
            const sessionId = this.getOrCreateSessionId();
            const userId = this.getOrCreateUserId();
            
            const requestBody = {
                appName: 'product_discovery_agent',
                userId: userId,
                sessionId: sessionId,
                newMessage: {
                    role: 'user',
                    parts: [
                        { text: query }
                    ]
                }
            };

            const response = await fetch(this.agentEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestBody),
                timeout: 10000
            });

            if (!response.ok) {
                throw new Error(`Agent search failed: ${response.status}`);
            }

            const data = await response.json();
            const products = this.parseAgentResponse(data);
            this.displayResults(query, products);
            
        } catch (error) {
            console.error('Agent search failed:', error);
            // Fallback: reload page to use server-side search
            window.location.reload();
        } finally {
            this.showLoading(false);
        }
    }

    async performAgentImageSearch(base64Data, mimeType) {
        this.showLoading(true);
        this.updateHeader('Image search', null, true);
        if (this.resultsContainer) {
            this.resultsContainer.style.display = 'none';
        }

        try {
            const sessionId = this.getOrCreateSessionId();
            const userId = this.getOrCreateUserId();
            const requestBody = {
                appName: 'product_discovery_agent',
                userId,
                sessionId,
                newMessage: {
                    role: 'user',
                    parts: [
                        // Provide parameters explicitly to align with FunctionTool schema
                        { functionCall: { name: 'pd_image_search', args: { image_base64: base64Data, mime_type: mimeType, top_k: 20, filters: {} } } }
                    ]
                }
            };

            const response = await fetch(this.agentEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
                timeout: 15000
            });

            if (!response.ok) {
                throw new Error(`Agent image search failed: ${response.status}`);
            }

            const data = await response.json();
            const products = this.parseAgentResponse(data);
            this.displayResults('Image', products);
        } catch (err) {
            console.error('Image search failed:', err);
            window.location.reload();
        } finally {
            // Clear image payload after one use
            sessionStorage.removeItem('search_image_data');
            sessionStorage.removeItem('search_image_type');
            this.showLoading(false);
        }
    }

    parseAgentResponse(agentData) {
        console.log('Parsing agent response');
        
        // Use the centralized agent response parser
        if (window.AgentResponseParser) {
            const parser = new window.AgentResponseParser();
            const parsedResponse = parser.parseResponse(agentData);
            
            // Extract products for search results display
            const products = parser.extractProducts(parsedResponse);
            if (products.length > 0) {
                console.log(`Found ${products.length} products from ${parsedResponse.type} response`);
                return products;
            }
            
            console.log('No products found in parsed response:', parsedResponse);
        }

        // Handle array format agent response
        if (Array.isArray(agentData) && agentData.length > 0) {
            let foundProducts = null;
            
            for (let i = 0; i < agentData.length; i++) {
                const item = agentData[i];
                
                if (item.content && item.content.parts) {
                    for (let j = 0; j < item.content.parts.length; j++) {
                        const part = item.content.parts[j];
                        
                        if (part.text && (part.text.includes('"products"') || part.text.includes('[{'))) {
                            try {
                                if (part.text.startsWith('{') && part.text.endsWith('}')) {
                                    const searchResults = JSON.parse(part.text);
                                    if (searchResults.products && Array.isArray(searchResults.products)) {
                                        foundProducts = searchResults.products.map(item => ({
                                            id: item.id || 'unknown',
                                            name: item.name || 'Unknown Product',
                                            description: item.description || '',
                                            picture: item.picture || item.product_image_url || '/static/img/products/placeholder.jpg'
                                        }));
                                    }
                                }
                            } catch (e) {
                                console.warn('Failed to parse JSON from text:', e);
                            }
                        }
                    }
                }
            }
            
            if (foundProducts) {
                return foundProducts;
            }
        }

        // Handle direct array response
        if (Array.isArray(agentData)) {
            return agentData.map(item => ({
                id: item.id || 'unknown',
                name: item.name || 'Unknown Product',
                description: item.description || '',
                picture: item.picture || item.product_image_url || '/static/img/products/placeholder.jpg'
            }));
        }
        
        console.warn('No products found in agent response');
        return [];
    }

    updateHeader(query, products, isLoading = false) {
        if (!this.headerContainer) return;
        
        let headerHTML;
        if (isLoading) {
            headerHTML = `
                <div class="col-12">
                    <div class="search-loading-spinner">
                        <div class="spinner"></div>
                    </div>
                </div>
            `;
        } else if (products && products.length > 0) {
            headerHTML = `
                <div class="col-12">
                    <h2>Search Results for "${query}"</h2>
                    <p class="text-muted">Found ${products.length} products</p>
                </div>
            `;
        } else {
            headerHTML = `
                <div class="col-12">
                    <h2>Search Results for "${query}"</h2>
                    <p class="text-muted">No products found. Try a different search term.</p>
                </div>
            `;
        }
        
        this.headerContainer.innerHTML = headerHTML;
    }

    displayResults(query, products) {
        console.log('Displaying results for query:', query);
        console.log('Products to display:', products);
        
        this.updateHeader(query, products);
        
        if (!this.resultsContainer) {
            console.error('Results container not found');
            return;
        }
        
        // Show the results container
        this.resultsContainer.style.display = 'flex';
        
        // Hide server-side fallback messages when AI search is active
        const fallbackContainer = document.querySelector('.server-side-fallback');
        if (fallbackContainer) {
            fallbackContainer.style.display = 'none';
        }
        
        if (!products || products.length === 0) {
            console.log('No products to display');
            this.resultsContainer.innerHTML = `
                <div class="col-12 text-center" style="padding: 4rem 0;">
                    <div style="color: #666; font-size: 1.2rem; margin-bottom: 1rem;">
                        <i class="fas fa-search" style="font-size: 3rem; margin-bottom: 1rem; display: block;"></i>
                        No products found for "${query}"
                    </div>
                    <p style="color: #888; font-size: 1rem; margin-bottom: 2rem;">
                        Try different keywords or browse our categories.
                    </p>
                </div>
            `;
            return;
        }

        // Display products
        console.log('Generating HTML for', products.length, 'products');
        let resultsHTML = '';
        products.forEach((product, index) => {
            console.log(`Processing product ${index}:`, product);
            resultsHTML += `
                <div class="col-6 col-md-4 col-lg-3 col-xl-2 hot-product-card" style="display:flex; flex-direction:column; align-items:center;">
                    <a href="/product/${product.id}" style="display:block; text-decoration:none; color:inherit; width:100%;">
                        <div class="hot-product-card-img" style="position:relative; width:100%; max-width:320px; margin:0 auto; aspect-ratio: 1 / 1; overflow:hidden; border-radius:24px; background:#f5f5f7;">
                            <img loading="lazy" decoding="async" src="${product.picture}" alt="${product.name}" style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover; display:block; image-rendering:auto;" onerror="this.src='/static/img/products/placeholder.jpg'" />
                            <div class="hot-product-card-img-overlay"></div>
                        </div>
                    </a>
                    <div style="width:100%; max-width:320px; margin:0 auto;">
                        <div class="hot-product-card-name">${this.escapeHtml(product.name)}</div>
                        <div class="hot-product-card-price">Loading price...</div>
                    </div>
                </div>
            `;
        });
        
        console.log('Setting innerHTML with HTML length:', resultsHTML.length);
        this.resultsContainer.innerHTML = resultsHTML;
        console.log('Results displayed successfully');
    }

    showLoading(show) {
        if (!this.loadingIndicator) return;
        
        if (show) {
            this.loadingIndicator.style.display = 'flex';
        } else {
            this.loadingIndicator.style.display = 'none';
        }
    }

    getOrCreateSessionId() {
        let sessionId = sessionStorage.getItem('search_session_id');
        if (!sessionId) {
            sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            sessionStorage.setItem('search_session_id', sessionId);
        }
        return sessionId;
    }

    getOrCreateUserId() {
        let userId = localStorage.getItem('user_id');
        if (!userId) {
            userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('user_id', userId);
        }
        return userId;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize search results when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Only initialize on search results page
    if (window.location.pathname === '/search') {
        new SearchResults();
    }
});
