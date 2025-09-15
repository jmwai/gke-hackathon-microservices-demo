/**
 * Smart Search functionality for Online Boutique
 * Provides natural language product search with agent integration and fallback
 */

class SmartSearch {
    constructor() {
        this.debounceTimeout = null;
        this.currentQuery = '';
        this.isAgentSearchEnabled = true; // Feature flag - can be controlled server-side
        this.agentEndpoint = '/api/agent-search';
        this.fallbackEndpoint = '/api/search'; // Traditional search fallback
        
        this.initializeElements();
        this.bindEvents();
        this.loadFeatureFlags();
    }

    initializeElements() {
        this.searchInput = document.getElementById('smart-search-input');
        this.searchBtn = document.getElementById('smart-search-btn');
        this.loadingIndicator = document.getElementById('search-loading');
        this.resultsContainer = document.getElementById('smart-search-results');
        this.suggestionsContainer = document.querySelector('.smart-search-suggestions');
    }

    bindEvents() {
        // Search button click
        this.searchBtn.addEventListener('click', () => this.performSearch());
        
        // Enter key in search input
        this.searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.performSearch();
            }
        });
        
        // Input debouncing for live search
        this.searchInput.addEventListener('input', (e) => {
            this.debounceSearch(e.target.value);
        });
        
        // Suggestion chips
        const suggestionChips = this.suggestionsContainer.querySelectorAll('.suggestion-chip');
        suggestionChips.forEach(chip => {
            chip.addEventListener('click', () => {
                const query = chip.getAttribute('data-query');
                this.searchInput.value = query;
                this.performSearch();
            });
        });
        
        // Click outside to close results
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.smart-search-container')) {
                this.hideResults();
            }
        });
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

    debounceSearch(query) {
        clearTimeout(this.debounceTimeout);
        this.debounceTimeout = setTimeout(() => {
            if (query.length >= 3) {
                this.performSearch(query);
            } else if (query.length === 0) {
                this.hideResults();
            }
        }, 300);
    }

    async performSearch(query = null) {
        const searchQuery = query || this.searchInput.value.trim();
        
        if (!searchQuery) {
            this.hideResults();
            return;
        }

        this.currentQuery = searchQuery;
        this.showLoading(true);
        
        try {
            let results;
            
            if (this.isAgentSearchEnabled) {
                // Try agent search first
                try {
                    results = await this.performAgentSearch(searchQuery);
                } catch (agentError) {
                    console.warn('Agent search failed, falling back to traditional search:', agentError);
                    results = await this.performFallbackSearch(searchQuery);
                    this.showFallbackMessage();
                }
            } else {
                // Use traditional search directly
                results = await this.performFallbackSearch(searchQuery);
            }
            
            this.displayResults(results);
            
        } catch (error) {
            console.error('Search failed:', error);
            this.showError('Sorry, search is temporarily unavailable. Please try again later.');
        } finally {
            this.showLoading(false);
        }
    }

    async performAgentSearch(query) {
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
            timeout: 10000 // 10 second timeout
        });

        if (!response.ok) {
            throw new Error(`Agent search failed: ${response.status}`);
        }

        const data = await response.json();
        return this.parseAgentResponse(data);
    }

    async performFallbackSearch(query) {
        // Simple keyword-based search as fallback
        const response = await fetch(`${this.fallbackEndpoint}?q=${encodeURIComponent(query)}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
            }
        });

        if (!response.ok) {
            throw new Error(`Fallback search failed: ${response.status}`);
        }

        const data = await response.json();
        return data.products || [];
    }

    parseAgentResponse(agentData) {
        console.log('Parsing agent response:', agentData);
        
        // Handle ADK agent response format
        if (agentData.candidates && agentData.candidates.length > 0) {
            const candidate = agentData.candidates[0];
            if (candidate.content && candidate.content.parts) {
                // Look for function call responses containing product data
                for (const part of candidate.content.parts) {
                    if (part.functionResponse && 
                        part.functionResponse.name === 'text_vector_search') {
                        try {
                            const response = part.functionResponse.response;
                            if (response && Array.isArray(response)) {
                                return response.map(item => ({
                                    id: item.id || 'unknown',
                                    name: item.name || 'Unknown Product',
                                    description: item.description || '',
                                    picture: item.picture || item.product_image_url || '/static/img/products/placeholder.jpg'
                                }));
                            }
                        } catch (e) {
                            console.warn('Failed to parse function response:', e);
                        }
                    }
                    
                    // Also check for text content that might contain structured data
                    if (part.text) {
                        try {
                            // Try to extract JSON from the text
                            const jsonMatch = part.text.match(/\[[\s\S]*\]/);
                            if (jsonMatch) {
                                const products = JSON.parse(jsonMatch[0]);
                                if (Array.isArray(products)) {
                                    return products.map(item => ({
                                        id: item.id || 'unknown',
                                        name: item.name || 'Unknown Product',
                                        description: item.description || '',
                                        picture: item.picture || item.product_image_url || '/static/img/products/placeholder.jpg'
                                    }));
                                }
                            }
                        } catch (e) {
                            // Not JSON, continue with text parsing
                        }
                        
                        // Fallback text parsing
                        return this.extractProductsFromText(part.text);
                    }
                }
            }
        }
        
        // Handle direct content response
        if (agentData.content) {
            return this.extractProductsFromText(agentData.content);
        }
        
        return [];
    }

    extractProductsFromText(text) {
        const products = [];
        
        // Try multiple parsing strategies
        
        // Strategy 1: Look for structured text patterns
        const productRegex = /(?:Product|Item):\s*([^\n]+)(?:\n|$)/gi;
        let match;
        while ((match = productRegex.exec(text)) !== null) {
            products.push({
                id: 'search-result-' + Math.random().toString(36).substr(2, 9),
                name: match[1].trim(),
                description: 'Found through AI search',
                picture: '/static/img/products/placeholder.jpg'
            });
        }
        
        // Strategy 2: Look for bullet points or numbered lists
        if (products.length === 0) {
            const lines = text.split('\n');
            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.match(/^[\d\-\*•][\.\)]*\s+(.+)$/)) {
                    const productName = trimmed.replace(/^[\d\-\*•][\.\)]*\s+/, '');
                    if (productName.length > 3) { // Filter out very short matches
                        products.push({
                            id: 'search-result-' + Math.random().toString(36).substr(2, 9),
                            name: productName,
                            description: 'Found through AI search',
                            picture: '/static/img/products/placeholder.jpg'
                        });
                    }
                }
            }
        }
        
        return products.slice(0, 10); // Limit to 10 results
    }

    displayResults(results) {
        this.resultsContainer.innerHTML = '';
        
        if (!results || results.length === 0) {
            this.resultsContainer.innerHTML = `
                <div class="search-fallback-message">
                    No products found for "${this.currentQuery}". Try a different search term.
                </div>
            `;
        } else {
            results.forEach(product => {
                const resultItem = this.createResultItem(product);
                this.resultsContainer.appendChild(resultItem);
            });
        }
        
        this.showResults();
    }

    createResultItem(product) {
        const item = document.createElement('div');
        item.className = 'search-result-item';
        item.onclick = () => this.navigateToProduct(product.id);
        
        item.innerHTML = `
            <img src="${product.picture || '/static/img/products/placeholder.jpg'}" 
                 alt="${product.name}" 
                 class="search-result-image"
                 onerror="this.src='/static/img/products/placeholder.jpg'">
            <div class="search-result-content">
                <div class="search-result-name">${this.escapeHtml(product.name)}</div>
                <div class="search-result-description">${this.escapeHtml(product.description || '')}</div>
            </div>
        `;
        
        return item;
    }

    navigateToProduct(productId) {
        window.location.href = `/product/${productId}`;
    }

    showLoading(show) {
        if (show) {
            this.searchBtn.style.display = 'none';
            this.loadingIndicator.style.display = 'flex';
        } else {
            this.searchBtn.style.display = 'flex';
            this.loadingIndicator.style.display = 'none';
        }
    }

    showResults() {
        this.resultsContainer.style.display = 'block';
    }

    hideResults() {
        this.resultsContainer.style.display = 'none';
    }

    showFallbackMessage() {
        const existingMessage = this.resultsContainer.querySelector('.search-fallback-message');
        if (!existingMessage) {
            const message = document.createElement('div');
            message.className = 'search-fallback-message';
            message.textContent = 'AI search temporarily unavailable - showing traditional search results';
            this.resultsContainer.insertBefore(message, this.resultsContainer.firstChild);
        }
    }

    showError(message) {
        this.resultsContainer.innerHTML = `
            <div class="search-error-message">
                ${this.escapeHtml(message)}
            </div>
        `;
        this.showResults();
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

// Initialize smart search when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new SmartSearch();
});
