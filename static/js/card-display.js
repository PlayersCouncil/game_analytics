/**
 * GEMP Card Analytics - Card Display Utilities
 * Card rendering, tooltips, and image handling
 */

/**
 * Default fallback image for cards without images
 */
const CARD_FALLBACK_IMAGE = '/static/images/card-back.png';

/**
 * Card catalog cache (populated by loadCatalog)
 */
let cardCatalog = {};

/**
 * Load and cache the card catalog
 */
async function loadCardCatalog() {
    try {
        const data = await GempAPI.loadCatalog();
        cardCatalog = data.cards || {};
        return cardCatalog;
    } catch (err) {
        console.error('Failed to load card catalog:', err);
        return {};
    }
}

/**
 * Get card info from catalog
 */
function getCardInfo(blueprint) {
    return cardCatalog[blueprint] || null;
}

/**
 * Get card name, with fallback to blueprint
 */
function getCardName(blueprint) {
    const info = getCardInfo(blueprint);
    return info?.card_name || blueprint;
}

/**
 * Get card image URL
 */
function getCardImageUrl(blueprint) {
    const info = getCardInfo(blueprint);
    return info?.image_url || CARD_FALLBACK_IMAGE;
}

/**
 * Get side display name
 */
function getSideDisplay(side) {
    if (side === 'free_peoples') return 'Free Peoples';
    if (side === 'shadow') return 'Shadow';
    return side || '(unknown)';
}

/**
 * Get side CSS class
 */
function getSideClass(side) {
    if (side === 'free_peoples') return 'side-fp';
    if (side === 'shadow') return 'side-shadow';
    return '';
}


/**
 * Card preview/tooltip system
 */
const CardPreview = {
    element: null,
    currentBlueprint: null,
    hideTimeout: null,

    /**
     * Initialize the preview system - call once on page load
     */
    init() {
        // Create preview element if it doesn't exist
        if (!this.element) {
            this.element = document.createElement('div');
            this.element.className = 'card-preview';
            this.element.innerHTML = '<img src="" alt="Card preview">';
            this.element.style.cssText = `
                display: none;
                position: fixed;
                z-index: 1000;
                pointer-events: none;
                background: var(--bg-dark);
                border: 2px solid var(--accent);
                border-radius: 8px;
                padding: 4px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            `;
            document.body.appendChild(this.element);
        }

        // Add global mouse tracking
        document.addEventListener('mousemove', (e) => {
            if (this.element.style.display === 'block') {
                this.position(e);
            }
        });
    },

    /**
     * Show preview for a card
     */
    show(blueprint, event) {
        if (this.hideTimeout) {
            clearTimeout(this.hideTimeout);
            this.hideTimeout = null;
        }

        const imageUrl = getCardImageUrl(blueprint);
        const img = this.element.querySelector('img');
        
        if (this.currentBlueprint !== blueprint) {
            img.src = imageUrl;
            img.onerror = () => { img.src = CARD_FALLBACK_IMAGE; };
            this.currentBlueprint = blueprint;
        }

        this.element.style.display = 'block';
        this.position(event);
    },

    /**
     * Hide the preview (with optional delay)
     */
    hide(delay = 100) {
        if (delay > 0) {
            this.hideTimeout = setTimeout(() => {
                this.element.style.display = 'none';
                this.currentBlueprint = null;
            }, delay);
        } else {
            this.element.style.display = 'none';
            this.currentBlueprint = null;
        }
    },

    /**
     * Position preview near cursor
     */
    position(event) {
        const padding = 15;
        const previewWidth = 250;
        const previewHeight = 350;

        let x = event.clientX + padding;
        let y = event.clientY + padding;

        // Keep on screen
        if (x + previewWidth > window.innerWidth) {
            x = event.clientX - previewWidth - padding;
        }
        if (y + previewHeight > window.innerHeight) {
            y = window.innerHeight - previewHeight - padding;
        }

        this.element.style.left = x + 'px';
        this.element.style.top = y + 'px';
    }
};


/**
 * Add card preview behavior to elements
 * Elements should have data-blueprint attribute
 */
function enableCardPreviews(containerSelector = 'body') {
    const container = document.querySelector(containerSelector);
    if (!container) return;

    container.addEventListener('mouseover', (e) => {
        const target = e.target.closest('[data-blueprint]');
        if (target) {
            CardPreview.show(target.dataset.blueprint, e);
        }
    });

    container.addEventListener('mouseout', (e) => {
        const target = e.target.closest('[data-blueprint]');
        if (target) {
            CardPreview.hide();
        }
    });
}


/**
 * Render a card name cell with preview support
 */
function renderCardNameCell(blueprint, additionalClasses = '') {
    const info = getCardInfo(blueprint);
    const name = info?.card_name || blueprint;
    const imageUrl = info?.image_url || CARD_FALLBACK_IMAGE;
    
    return `
        <span class="card-name ${additionalClasses}" 
              data-blueprint="${blueprint}"
              data-image="${imageUrl}">
            ${escapeHtml(name)}
        </span>
        <span class="blueprint">${blueprint}</span>
    `;
}


/**
 * Render a mini card badge (used in archetype displays)
 */
function renderCardBadge(blueprint, options = {}) {
    const info = getCardInfo(blueprint);
    const name = info?.card_name || blueprint;
    const imageUrl = info?.image_url || CARD_FALLBACK_IMAGE;
    const sideClass = getSideClass(info?.side);
    
    const classes = ['card-badge', sideClass];
    if (options.isCore) classes.push('core');
    if (options.isFlex) classes.push('flex');
    if (options.className) classes.push(options.className);

    return `
        <span class="${classes.join(' ')}" 
              data-blueprint="${blueprint}"
              data-image="${imageUrl}"
              title="${escapeHtml(name)}">
            ${escapeHtml(name)}
        </span>
    `;
}


/**
 * HTML escaping utility
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


// Initialize preview system when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => CardPreview.init());
} else {
    CardPreview.init();
}
