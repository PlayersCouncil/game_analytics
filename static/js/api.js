/**
 * GEMP Card Analytics - API Utilities
 * Shared fetch wrappers, error handling, and common API patterns
 */

const GempAPI = {
    /**
     * Base fetch wrapper with error handling
     */
    async fetch(url, options = {}) {
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }
            return await response.json();
        } catch (err) {
            console.error(`API error for ${url}:`, err);
            throw err;
        }
    },

    /**
     * Load card catalog
     * Returns: { cards: { blueprint: { name, culture, side, ... } } }
     */
    async loadCatalog() {
        return this.fetch('/api/catalog');
    },

    /**
     * Load balance patches
     * Returns: { patches: [{ id, patch_name, patch_date, notes }] }
     */
    async loadPatches() {
        const data = await this.fetch('/api/patches');
        // Sort by date descending (newest first)
        data.patches.sort((a, b) => new Date(b.patch_date) - new Date(a.patch_date));
        return data;
    },

    /**
     * Load system stats summary
     * Returns: { total_games, total_cards, ... }
     */
    async loadStats() {
        return this.fetch('/api/stats/summary');
    },

    /**
     * Query card statistics
     */
    async queryCards(params) {
        const queryString = new URLSearchParams(params).toString();
        return this.fetch(`/api/stats/cards?${queryString}`);
    },

    /**
     * Load archetypes for a format/side
     */
    async loadArchetypes(format, side) {
        const params = new URLSearchParams({ format, side });
        return this.fetch(`/api/archetypes?${params}`);
    },

    /**
     * Load archetype details
     */
    async loadArchetypeDetails(id) {
        return this.fetch(`/api/archetypes/${id}`);
    }
};


/**
 * Format dropdown options - consistent across all pages
 */
const FORMAT_OPTIONS = {
    pc: [
        { value: 'Movie Block (PC)', label: 'PC-Movie' },
        { value: 'Fellowship Block (PC)', label: 'PC-Fellowship' },
        { value: 'Expanded (PC)', label: 'PC-Expanded' }
    ],
    decipher: [
        { value: 'Movie Block', label: 'Movie Block' },
        { value: 'Fellowship Block', label: 'Fellowship Block' },
        { value: 'Expanded', label: 'Expanded' },
        { value: 'Towers Standard', label: 'Towers Standard' },
        { value: 'Towers Block', label: 'Towers Block' }
    ],
    sealed: [
        { value: 'Limited - FOTR', label: 'Limited - FOTR' },
        { value: 'Limited - TTT', label: 'Limited - TTT' },
        { value: 'Limited - ROTK', label: 'Limited - ROTK' },
        { value: 'Limited - WOTR', label: 'Limited - WOTR' },
        { value: 'Limited - TH', label: 'Limited - TH' }
    ]
};

/**
 * Populate a format select element with optgroups
 */
function populateFormatSelect(selectElement, defaultValue = 'Movie Block (PC)') {
    selectElement.innerHTML = `
        <optgroup label="PC Formats">
            ${FORMAT_OPTIONS.pc.map(f => 
                `<option value="${f.value}" ${f.value === defaultValue ? 'selected' : ''}>${f.label}</option>`
            ).join('')}
        </optgroup>
        <optgroup label="Main Decipher Formats">
            ${FORMAT_OPTIONS.decipher.map(f => 
                `<option value="${f.value}" ${f.value === defaultValue ? 'selected' : ''}>${f.label}</option>`
            ).join('')}
        </optgroup>
        <optgroup label="Sealed Formats">
            ${FORMAT_OPTIONS.sealed.map(f => 
                `<option value="${f.value}" ${f.value === defaultValue ? 'selected' : ''}>${f.label}</option>`
            ).join('')}
        </optgroup>
    `;
}


/**
 * Set mapping - convert set numbers to display names
 */
const SET_NAMES = {
    0: 'Promo',
    1: 'Fellowship',
    2: 'Mines of Moria',
    3: 'Realms of the Elf-lords',
    4: 'The Two Towers',
    5: 'Battle of Helm\'s Deep',
    6: 'Ents of Fangorn',
    7: 'Return of the King',
    8: 'Siege of Gondor',
    9: 'Reflections',
    10: 'Mount Doom',
    11: 'Shadows',
    12: 'Black Rider',
    13: 'Bloodlines',
    14: 'Expanded Middle-earth',
    15: 'The Hunters',
    16: 'The Wraith Collection',
    17: 'Rise of Saruman',
    18: 'Treachery & Deceit',
    19: 'Ages End',
    // Hobbit Draft sets
    30: 'Hobbit Draft - Main',
    31: 'Hobbit Draft - Treasure',
    32: 'Hobbit Draft - Supplementary',
    // PC V-sets
    100: 'V0 - PC Base',
    101: 'V1 - Errata',
    102: 'V2 - Rise of the Witch-King',
    103: 'V3 - Tales of Arda'
};

/**
 * Normalize set number (handle errata mappings)
 */
function normalizeSetNumber(setNum) {
    if (setNum === null || setNum === undefined) return null;
    // Map errata sets 50-69 back to 0-19
    if (setNum >= 50 && setNum <= 69) {
        return setNum - 50;
    }
    // Map old playtest V-sets 150+ to 100+
    if (setNum >= 150) {
        return setNum - 50;
    }
    return setNum;
}

/**
 * Get display name for a set number
 */
function getSetDisplay(setNum) {
    if (setNum === null || setNum === undefined) return '(unknown)';
    const normalized = normalizeSetNumber(setNum);
    return SET_NAMES[normalized] || `Set ${normalized}`;
}


/**
 * Win rate formatting utilities
 */
function formatWinRate(wr) {
    if (wr === null || wr === undefined) return '-';
    return (wr * 100).toFixed(1) + '%';
}

function getWinRateClass(wr) {
    if (wr === null || wr === undefined) return '';
    if (wr >= 0.52) return 'wr-positive';
    if (wr <= 0.48) return 'wr-negative';
    return 'wr-neutral';
}


/**
 * Date utilities
 */
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString();
}

function getDefaultDateRange(daysBack = 90) {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - daysBack);
    return {
        start: start.toISOString().split('T')[0],
        end: end.toISOString().split('T')[0]
    };
}


/**
 * URL state management - save/restore filters to URL
 */
const URLState = {
    save(params) {
        const url = new URL(window.location);
        Object.entries(params).forEach(([key, value]) => {
            if (value !== null && value !== undefined && value !== '') {
                url.searchParams.set(key, value);
            } else {
                url.searchParams.delete(key);
            }
        });
        window.history.replaceState({}, '', url);
    },

    load() {
        const params = {};
        new URL(window.location).searchParams.forEach((value, key) => {
            params[key] = value;
        });
        return params;
    },

    get(key, defaultValue = null) {
        return new URL(window.location).searchParams.get(key) || defaultValue;
    }
};


/**
 * Copy to clipboard with visual feedback
 */
async function copyToClipboard(text, buttonElement = null) {
    try {
        await navigator.clipboard.writeText(text);
        if (buttonElement) {
            const originalText = buttonElement.textContent;
            buttonElement.textContent = 'Copied!';
            buttonElement.classList.add('copied');
            setTimeout(() => {
                buttonElement.textContent = originalText;
                buttonElement.classList.remove('copied');
            }, 2000);
        }
        return true;
    } catch (err) {
        console.error('Failed to copy:', err);
        return false;
    }
}


/**
 * Debounce utility for search inputs
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}


/**
 * Format large numbers with commas
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '-';
    return num.toLocaleString();
}
