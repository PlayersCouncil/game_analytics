/**
 * GEMP Card Analytics - Filter Controls
 * Reusable filter UI components for format, dates, patches, and tiers
 */

/**
 * Patch selector component
 * Loads patches and populates a select element, with date range integration
 */
class PatchSelector {
    constructor(selectElement, startDateInput, endDateInput, onChangeCallback) {
        this.select = typeof selectElement === 'string' 
            ? document.querySelector(selectElement) 
            : selectElement;
        this.startDate = typeof startDateInput === 'string'
            ? document.querySelector(startDateInput)
            : startDateInput;
        this.endDate = typeof endDateInput === 'string'
            ? document.querySelector(endDateInput)
            : endDateInput;
        this.onChange = onChangeCallback;
        this.patches = [];

        if (this.select) {
            this.select.addEventListener('change', () => this.handleChange());
        }
    }

    async load() {
        try {
            const data = await GempAPI.loadPatches();
            this.patches = data.patches;
            this.render();
            return this.patches;
        } catch (err) {
            console.error('Failed to load patches:', err);
            return [];
        }
    }

    render() {
        if (!this.select) return;

        // Clear and add default option
        this.select.innerHTML = '<option value="">Custom Date Range</option>';

        // Add patch options
        this.patches.forEach((patch, idx) => {
            const option = document.createElement('option');
            option.value = idx.toString();
            option.textContent = `${patch.patch_name} (${patch.patch_date})`;
            this.select.appendChild(option);
        });
    }

    handleChange() {
        const idx = this.select.value;
        
        if (idx === '' || idx === null) {
            // Custom date range - don't change date inputs
            if (this.onChange) this.onChange(null);
            return;
        }

        const patch = this.patches[parseInt(idx)];
        if (!patch) return;

        // Set date range based on patch
        const patchDate = new Date(patch.patch_date);
        const nextPatchIdx = parseInt(idx) - 1; // Patches are sorted newest first
        
        if (this.startDate) {
            this.startDate.value = patch.patch_date;
        }
        
        if (this.endDate) {
            if (nextPatchIdx >= 0 && this.patches[nextPatchIdx]) {
                // End date is day before next patch
                const nextDate = new Date(this.patches[nextPatchIdx].patch_date);
                nextDate.setDate(nextDate.getDate() - 1);
                this.endDate.value = nextDate.toISOString().split('T')[0];
            } else {
                // No next patch - use today
                this.endDate.value = new Date().toISOString().split('T')[0];
            }
        }

        if (this.onChange) this.onChange(patch);
    }

    /**
     * Called when dates are manually changed - clear patch selection
     */
    clearSelection() {
        if (this.select) {
            this.select.value = '';
        }
    }

    /**
     * Get currently selected patch (or null)
     */
    getSelected() {
        const idx = this.select?.value;
        if (!idx || idx === '') return null;
        return this.patches[parseInt(idx)] || null;
    }
}


/**
 * Tier filter component
 * Manages outcome and competitive tier checkboxes
 */
class TierFilter {
    constructor(containerSelector, tierType, onChangeCallback) {
        this.container = typeof containerSelector === 'string'
            ? document.querySelector(containerSelector)
            : containerSelector;
        this.tierType = tierType; // 'outcome' or 'competitive'
        this.onChange = onChangeCallback;
        this.checkboxes = [];

        if (this.container) {
            this.checkboxes = Array.from(
                this.container.querySelectorAll('input[type="checkbox"]')
            );
            this.checkboxes.forEach(cb => {
                cb.addEventListener('change', () => {
                    if (this.onChange) this.onChange(this.getSelected());
                });
            });
        }
    }

    getSelected() {
        return this.checkboxes
            .filter(cb => cb.checked)
            .map(cb => parseInt(cb.value));
    }

    setSelected(values) {
        this.checkboxes.forEach(cb => {
            cb.checked = values.includes(parseInt(cb.value));
        });
    }

    selectAll() {
        this.checkboxes.forEach(cb => cb.checked = true);
        if (this.onChange) this.onChange(this.getSelected());
    }

    selectNone() {
        this.checkboxes.forEach(cb => cb.checked = false);
        if (this.onChange) this.onChange(this.getSelected());
    }

    /**
     * Get as comma-separated string for API
     */
    toApiParam() {
        const selected = this.getSelected();
        return selected.length > 0 ? selected.join(',') : null;
    }
}


/**
 * Combined filter state manager
 * Coordinates format, dates, patches, and tiers
 */
class FilterManager {
    constructor(options = {}) {
        this.format = options.formatSelect 
            ? document.querySelector(options.formatSelect) 
            : null;
        this.startDate = options.startDate
            ? document.querySelector(options.startDate)
            : null;
        this.endDate = options.endDate
            ? document.querySelector(options.endDate)
            : null;
        this.onChange = options.onChange || null;

        // Initialize patch selector
        this.patchSelector = options.patchSelect 
            ? new PatchSelector(
                options.patchSelect,
                this.startDate,
                this.endDate,
                () => this.triggerChange()
            )
            : null;

        // Initialize tier filters
        this.outcomeTier = options.outcomeTierContainer
            ? new TierFilter(options.outcomeTierContainer, 'outcome', () => this.triggerChange())
            : null;
        this.competitiveTier = options.competitiveTierContainer
            ? new TierFilter(options.competitiveTierContainer, 'competitive', () => this.triggerChange())
            : null;

        // Bind format change
        if (this.format) {
            this.format.addEventListener('change', () => this.triggerChange());
        }

        // Bind date changes - clear patch selection on manual date change
        if (this.startDate) {
            this.startDate.addEventListener('change', () => {
                if (this.patchSelector) this.patchSelector.clearSelection();
                this.triggerChange();
            });
        }
        if (this.endDate) {
            this.endDate.addEventListener('change', () => {
                if (this.patchSelector) this.patchSelector.clearSelection();
                this.triggerChange();
            });
        }
    }

    async init() {
        // Load patches
        if (this.patchSelector) {
            await this.patchSelector.load();
        }

        // Set default dates
        const defaults = getDefaultDateRange(90);
        if (this.startDate && !this.startDate.value) {
            this.startDate.value = defaults.start;
        }
        if (this.endDate && !this.endDate.value) {
            this.endDate.value = defaults.end;
        }

        // Load from URL state
        this.loadFromURL();
    }

    getState() {
        return {
            format: this.format?.value || null,
            start: this.startDate?.value || null,
            end: this.endDate?.value || null,
            patch: this.patchSelector?.getSelected()?.patch_name || null,
            outcomeTiers: this.outcomeTier?.getSelected() || [],
            competitiveTiers: this.competitiveTier?.getSelected() || []
        };
    }

    /**
     * Get state as API query parameters
     */
    toApiParams() {
        const state = this.getState();
        const params = {};

        if (state.format) params.format = state.format;
        if (state.start) params.start = state.start;
        if (state.end) params.end = state.end;
        if (state.outcomeTiers.length > 0) {
            params.outcome_tier = state.outcomeTiers.join(',');
        }
        if (state.competitiveTiers.length > 0) {
            params.competitive_tier = state.competitiveTiers.join(',');
        }

        return params;
    }

    /**
     * Save current state to URL
     */
    saveToURL() {
        URLState.save(this.toApiParams());
    }

    /**
     * Load state from URL parameters
     */
    loadFromURL() {
        const params = URLState.load();

        if (params.format && this.format) {
            this.format.value = params.format;
        }
        if (params.start && this.startDate) {
            this.startDate.value = params.start;
        }
        if (params.end && this.endDate) {
            this.endDate.value = params.end;
        }
        if (params.outcome_tier && this.outcomeTier) {
            this.outcomeTier.setSelected(params.outcome_tier.split(',').map(Number));
        }
        if (params.competitive_tier && this.competitiveTier) {
            this.competitiveTier.setSelected(params.competitive_tier.split(',').map(Number));
        }
    }

    triggerChange() {
        if (this.onChange) {
            this.onChange(this.getState());
        }
    }
}


/**
 * Render tier checkboxes HTML
 * Helper for pages that need to generate the tier UI dynamically
 */
function renderOutcomeTierCheckboxes(containerId = 'outcomeTiers') {
    return `
        <div id="${containerId}" class="checkbox-group vertical">
            <label title="Clear game-ending: Site 9 survival, Ring-bearer corrupted or killed">
                <input type="checkbox" value="1" checked> Decisive
            </label>
            <label title="Concession at site 6+">
                <input type="checkbox" value="2" checked> Late Concession
            </label>
            <label title="Early quit, timeout, or unclear">
                <input type="checkbox" value="3"> Ambiguous
            </label>
        </div>
    `;
}

function renderCompetitiveTierCheckboxes(containerId = 'competitiveTiers') {
    return `
        <div id="${containerId}" class="checkbox-group vertical">
            <label>
                <input type="checkbox" value="1" checked> Casual
            </label>
            <label>
                <input type="checkbox" value="2" checked> League
            </label>
            <label>
                <input type="checkbox" value="3" checked> Tournament
            </label>
            <label>
                <input type="checkbox" value="4" checked> Championship
            </label>
        </div>
    `;
}
