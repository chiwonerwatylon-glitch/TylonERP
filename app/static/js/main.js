/*
 * ============================================================================
 * TylonERP - Professional JavaScript Application
 * Version: 1.0.0
 * Brand: Multi-tenant Stock, Revenue & Debtor Management System
 * Framework: Vanilla JS (ES6+) with Bootstrap 5.3.3
 * ============================================================================
 */

'use strict';

/* ============================================================================
   1. GLOBAL APP CONFIGURATION
   ============================================================================ */

const TylonERP = window.TylonERP || {
    version: '1.0.0',
    apiBaseUrl: '/api/v1',
    debug: false,
    
    // Configuration
    config: {
        defaultTimeZone: 'UTC',
        dateFormat: 'YYYY-MM-DD',
        timeFormat: 'HH:mm:ss',
        currency: 'USD',
        currencySymbol: '$',
        locale: 'en-US',
        darkTheme: true,
        animationsEnabled: true,
        notificationDuration: 5000,
    },
    
    // Module storage
    modules: {},
    
    // Utility methods
    log(...args) {
        if (this.debug) {
            console.log('[TylonERP]', ...args);
        }
    },
    
    error(...args) {
        console.error('[TylonERP Error]', ...args);
    },
    
    warn(...args) {
        console.warn('[TylonERP Warning]', ...args);
    },
};

/* ============================================================================
   2. UTILITY FUNCTIONS
   ============================================================================ */

const Utils = {
    /**
     * Generate unique ID
     */
    generateId() {
        return 'id_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    },
    
    /**
     * Deep clone object
     */
    deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    },
    
    /**
     * Merge objects
     */
    merge(target, source) {
        return { ...target, ...source };
    },
    
    /**
     * Debounce function
     */
    debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    /**
     * Throttle function
     */
    throttle(func, limit = 300) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },
    
    /**
     * Format currency
     */
    formatCurrency(amount, currency = '$') {
        return currency + parseFloat(amount).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    },
    
    /**
     * Format date
     */
    formatDate(date, format = 'MMM DD, YYYY') {
        const d = new Date(date);
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        
        const map = {
            YYYY: d.getFullYear(),
            MM: String(d.getMonth() + 1).padStart(2, '0'),
            MMM: months[d.getMonth()],
            DD: String(d.getDate()).padStart(2, '0'),
            HH: String(d.getHours()).padStart(2, '0'),
            mm: String(d.getMinutes()).padStart(2, '0'),
            ss: String(d.getSeconds()).padStart(2, '0'),
        };
        
        return format.replace(/YYYY|MM|MMM|DD|HH|mm|ss/g, (match) => map[match]);
    },
    
    /**
     * Format file size
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    },
    
    /**
     * Validate email
     */
    validateEmail(email) {
        const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return regex.test(email);
    },
    
    /**
     * Validate phone
     */
    validatePhone(phone) {
        const regex = /^[\d\-\+\(\)\s]+$/;
        return regex.test(phone) && phone.replace(/\D/g, '').length >= 10;
    },
    
    /**
     * Validate URL
     */
    validateUrl(url) {
        try {
            new URL(url);
            return true;
        } catch (e) {
            return false;
        }
    },
    
    /**
     * Copy to clipboard
     */
    copyToClipboard(text) {
        return navigator.clipboard.writeText(text).then(() => {
            Notifications.success('Copied to clipboard');
        }).catch(err => {
            Notifications.error('Failed to copy');
            console.error('Clipboard error:', err);
        });
    },
    
    /**
     * Get query parameter
     */
    getQueryParam(param) {
        const params = new URLSearchParams(window.location.search);
        return params.get(param);
    },
    
    /**
     * Get all query parameters
     */
    getAllQueryParams() {
        const params = new URLSearchParams(window.location.search);
        const obj = {};
        for (let [key, value] of params) {
            obj[key] = value;
        }
        return obj;
    },
    
    /**
     * Update query parameters
     */
    updateQueryParam(param, value) {
        const params = new URLSearchParams(window.location.search);
        params.set(param, value);
        window.history.replaceState({}, '', `${window.location.pathname}?${params}`);
    },
    
    /**
     * Parse JSON safely
     */
    parseJSON(jsonString, fallback = null) {
        try {
            return JSON.parse(jsonString);
        } catch (e) {
            console.error('JSON parse error:', e);
            return fallback;
        }
    },
    
    /**
     * Check if element is in viewport
     */
    isInViewport(element) {
        const rect = element.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth)
        );
    },
    
    /**
     * Scroll to element
     */
    scrollTo(element, offset = 0) {
        const elementPosition = element.getBoundingClientRect().top + window.scrollY - offset;
        window.scrollTo({ top: elementPosition, behavior: 'smooth' });
    },
    
    /**
     * Get localStorage item
     */
    getStorage(key, fallback = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : fallback;
        } catch (e) {
            return fallback;
        }
    },
    
    /**
     * Set localStorage item
     */
    setStorage(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.error('Storage error:', e);
            return false;
        }
    },
    
    /**
     * Remove localStorage item
     */
    removeStorage(key) {
        try {
            localStorage.removeItem(key);
            return true;
        } catch (e) {
            console.error('Storage error:', e);
            return false;
        }
    },
    
    /**
     * Clear all localStorage
     */
    clearStorage() {
        try {
            localStorage.clear();
            return true;
        } catch (e) {
            console.error('Storage error:', e);
            return false;
        }
    },
};

/* ============================================================================
   3. NOTIFICATION SYSTEM
   ============================================================================ */

const Notifications = {
    /**
     * Show success notification
     */
    success(message, duration = TylonERP.config.notificationDuration) {
        this.show('success', message, duration);
    },
    
    /**
     * Show error notification
     */
    error(message, duration = TylonERP.config.notificationDuration) {
        this.show('error', message, duration);
    },
    
    /**
     * Show warning notification
     */
    warning(message, duration = TylonERP.config.notificationDuration) {
        this.show('warning', message, duration);
    },
    
    /**
     * Show info notification
     */
    info(message, duration = TylonERP.config.notificationDuration) {
        this.show('info', message, duration);
    },
    
    /**
     * Show notification (internal)
     */
    show(type, message, duration) {
        if (window.toastr) {
            toastr[type](message);
        } else {
            // Fallback to console
            console[type === 'error' ? 'error' : 'log'](`[${type.toUpperCase()}]`, message);
        }
    },
    
    /**
     * Confirm dialog
     */
    confirm(message, onConfirm, onCancel) {
        if (window.confirm(message)) {
            onConfirm && onConfirm();
        } else {
            onCancel && onCancel();
        }
    },
    
    /**
     * Alert dialog
     */
    alert(message, type = 'info') {
        alert(message);
    },
};

/* ============================================================================
   4. API SERVICE
   ============================================================================ */

const API = {
    /**
     * Make API request
     */
    async request(endpoint, options = {}) {
        const defaultOptions = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'include',
        };
        
        const mergedOptions = { ...defaultOptions, ...options };
        const url = `${TylonERP.apiBaseUrl}${endpoint}`;
        
        TylonERP.log('API Request:', url, mergedOptions);
        
        try {
            const response = await fetch(url, mergedOptions);
            
            if (!response.ok) {
                const error = new Error(`API Error: ${response.statusText}`);
                error.status = response.status;
                throw error;
            }
            
            const data = await response.json();
            TylonERP.log('API Response:', data);
            return data;
        } catch (error) {
            TylonERP.error('API Request failed:', error);
            throw error;
        }
    },
    
    /**
     * GET request
     */
    get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        return this.request(url, { method: 'GET' });
    },
    
    /**
     * POST request
     */
    post(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },
    
    /**
     * PUT request
     */
    put(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },
    
    /**
     * DELETE request
     */
    delete(endpoint) {
        return this.request(endpoint, {
            method: 'DELETE',
        });
    },
    
    /**
     * PATCH request
     */
    patch(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    },
    
    /**
     * Upload file
     */
    async uploadFile(endpoint, file) {
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch(`${TylonERP.apiBaseUrl}${endpoint}`, {
                method: 'POST',
                body: formData,
                credentials: 'include',
            });
            
            if (!response.ok) {
                throw new Error(`Upload failed: ${response.statusText}`);
            }
            
            return await response.json();
        } catch (error) {
            TylonERP.error('File upload failed:', error);
            throw error;
        }
    },
};

/* ============================================================================
   5. DOM HELPERS
   ============================================================================ */

const DOM = {
    /**
     * Select element
     */
    select(selector) {
        return document.querySelector(selector);
    },
    
    /**
     * Select all elements
     */
    selectAll(selector) {
        return document.querySelectorAll(selector);
    },
    
    /**
     * Get element by ID
     */
    byId(id) {
        return document.getElementById(id);
    },
    
    /**
     * Create element
     */
    create(tag, classes = '', attributes = {}) {
        const element = document.createElement(tag);
        if (classes) {
            element.className = classes;
        }
        Object.entries(attributes).forEach(([key, value]) => {
            if (key === 'text') {
                element.textContent = value;
            } else if (key === 'html') {
                element.innerHTML = value;
            } else {
                element.setAttribute(key, value);
            }
        });
        return element;
    },
    
    /**
     * Add class
     */
    addClass(element, className) {
        element.classList.add(className);
    },
    
    /**
     * Remove class
     */
    removeClass(element, className) {
        element.classList.remove(className);
    },
    
    /**
     * Toggle class
     */
    toggleClass(element, className) {
        element.classList.toggle(className);
    },
    
    /**
     * Has class
     */
    hasClass(element, className) {
        return element.classList.contains(className);
    },
    
    /**
     * Add event listener
     */
    on(element, event, handler) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.addEventListener(event, handler);
        }
    },
    
    /**
     * Remove event listener
     */
    off(element, event, handler) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.removeEventListener(event, handler);
        }
    },
    
    /**
     * Delegate event
     */
    delegate(parent, selector, event, handler) {
        if (typeof parent === 'string') {
            parent = this.select(parent);
        }
        parent.addEventListener(event, (e) => {
            const target = e.target.closest(selector);
            if (target) {
                handler.call(target, e);
            }
        });
    },
    
    /**
     * Show element
     */
    show(element) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.style.display = '';
            element.classList.remove('d-none');
        }
    },
    
    /**
     * Hide element
     */
    hide(element) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.classList.add('d-none');
        }
    },
    
    /**
     * Toggle visibility
     */
    toggle(element) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.classList.toggle('d-none');
        }
    },
    
    /**
     * Set HTML
     */
    setHTML(element, html) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.innerHTML = html;
        }
    },
    
    /**
     * Get HTML
     */
    getHTML(element) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        return element ? element.innerHTML : '';
    },
    
    /**
     * Set text
     */
    setText(element, text) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.textContent = text;
        }
    },
    
    /**
     * Get text
     */
    getText(element) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        return element ? element.textContent : '';
    },
    
    /**
     * Set attribute
     */
    setAttr(element, attr, value) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.setAttribute(attr, value);
        }
    },
    
    /**
     * Get attribute
     */
    getAttr(element, attr) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        return element ? element.getAttribute(attr) : null;
    },
    
    /**
     * Set style
     */
    setStyle(element, styles) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            Object.entries(styles).forEach(([key, value]) => {
                element.style[key] = value;
            });
        }
    },
    
    /**
     * Get style
     */
    getStyle(element, property) {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        return element ? getComputedStyle(element)[property] : null;
    },
    
    /**
     * Get form data
     */
    getFormData(form) {
        if (typeof form === 'string') {
            form = this.select(form);
        }
        const formData = new FormData(form);
        const data = {};
        for (let [key, value] of formData) {
            data[key] = value;
        }
        return data;
    },
    
    /**
     * Set form data
     */
    setFormData(form, data) {
        if (typeof form === 'string') {
            form = this.select(form);
        }
        Object.entries(data).forEach(([key, value]) => {
            const field = form.elements[key];
            if (field) {
                field.value = value;
            }
        });
    },
    
    /**
     * Clear form
     */
    clearForm(form) {
        if (typeof form === 'string') {
            form = this.select(form);
        }
        if (form) {
            form.reset();
        }
    },
    
    /**
     * Show loading state
     */
    showLoading(element, message = 'Loading...') {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.disabled = true;
            element.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status"></span>
                ${message}
            `;
        }
    },
    
    /**
     * Hide loading state
     */
    hideLoading(element, text = 'Save') {
        if (typeof element === 'string') {
            element = this.select(element);
        }
        if (element) {
            element.disabled = false;
            element.textContent = text;
        }
    },
};

/* ============================================================================
   6. MODAL MANAGER
   ============================================================================ */

const Modals = {
    /**
     * Show modal
     */
    show(selector) {
        const modal = DOM.select(selector);
        if (modal && window.bootstrap) {
            const bootstrapModal = new bootstrap.Modal(modal);
            bootstrapModal.show();
        }
    },
    
    /**
     * Hide modal
     */
    hide(selector) {
        const modal = DOM.select(selector);
        if (modal && window.bootstrap) {
            const bootstrapModal = bootstrap.Modal.getInstance(modal);
            if (bootstrapModal) {
                bootstrapModal.hide();
            }
        }
    },
    
    /**
     * Toggle modal
     */
    toggle(selector) {
        const modal = DOM.select(selector);
        if (modal) {
            DOM.toggleClass(modal, 'show');
        }
    },
};

/* ============================================================================
   7. TABLE MANAGER
   ============================================================================ */

const Tables = {
    /**
     * Initialize DataTable
     */
    init(selector, options = {}) {
        const defaultOptions = {
            responsive: true,
            pageLength: 10,
            language: {
                emptyTable: 'No data available',
                info: 'Showing _START_ to _END_ of _TOTAL_ entries',
                infoEmpty: 'Showing 0 to 0 of 0 entries',
                infoFiltered: '(filtered from _MAX_ total entries)',
                paginate: {
                    first: 'First',
                    previous: 'Previous',
                    next: 'Next',
                    last: 'Last',
                },
                search: 'Search:',
            },
        };
        
        const finalOptions = { ...defaultOptions, ...options };
        
        if (window.$ && window.$.fn.DataTable) {
            return $(selector).DataTable(finalOptions);
        }
    },
    
    /**
     * Reload table
     */
    reload(table) {
        if (table) {
            table.ajax.reload();
        }
    },
    
    /**
     * Add row to table
     */
    addRow(table, data) {
        if (table) {
            table.row.add(data).draw(false);
        }
    },
    
    /**
     * Remove row from table
     */
    removeRow(table, index) {
        if (table) {
            table.row(index).remove().draw(false);
        }
    },
    
    /**
     * Clear table
     */
    clear(table) {
        if (table) {
            table.clear().draw();
        }
    },
};

/* ============================================================================
   8. THEME MANAGER
   ============================================================================ */

const Theme = {
    /**
     * Initialize theme
     */
    init() {
        const savedTheme = Utils.getStorage('ripple-theme', 'dark');
        this.set(savedTheme);
        
        // Listen for theme toggle button
        const themeToggle = DOM.select('#themeToggle');
        if (themeToggle) {
            DOM.on(themeToggle, 'click', () => this.toggle());
        }
    },
    
    /**
     * Set theme
     */
    set(theme) {
        document.documentElement.setAttribute('data-bs-theme', theme);
        Utils.setStorage('ripple-theme', theme);
        
        // Update icon
        const themeToggle = DOM.select('#themeToggle');
        if (themeToggle) {
            const icon = theme === 'dark' ? 'sun-fill' : 'moon-fill';
            themeToggle.innerHTML = `<i class="bi bi-${icon}"></i>`;
        }
    },
    
    /**
     * Toggle theme
     */
    toggle() {
        const currentTheme = document.documentElement.getAttribute('data-bs-theme') || 'dark';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        this.set(newTheme);
    },
    
    /**
     * Get current theme
     */
    getCurrent() {
        return document.documentElement.getAttribute('data-bs-theme') || 'dark';
    },
};

/* ============================================================================
   9. FORM VALIDATOR
   ============================================================================ */

const FormValidator = {
    /**
     * Validate form
     */
    validate(form) {
        if (typeof form === 'string') {
            form = DOM.select(form);
        }
        
        let isValid = true;
        const inputs = form.querySelectorAll('input, textarea, select');
        
        inputs.forEach(input => {
            if (!this.validateInput(input)) {
                isValid = false;
            }
        });
        
        return isValid;
    },
    
    /**
     * Validate single input
     */
    validateInput(input) {
        let isValid = true;
        const value = input.value.trim();
        const type = input.type;
        const required = input.hasAttribute('required');
        
        // Clear previous errors
        DOM.removeClass(input, 'is-invalid');
        const errorMsg = input.parentElement.querySelector('.invalid-feedback');
        if (errorMsg) {
            DOM.hide(errorMsg);
        }
        
        // Check required
        if (required && !value) {
            this.showError(input, 'This field is required');
            isValid = false;
        }
        
        // Check type-specific validation
        if (value && !isValid) {
            switch (type) {
                case 'email':
                    if (!Utils.validateEmail(value)) {
                        this.showError(input, 'Please enter a valid email');
                        isValid = false;
                    }
                    break;
                case 'tel':
                    if (!Utils.validatePhone(value)) {
                        this.showError(input, 'Please enter a valid phone number');
                        isValid = false;
                    }
                    break;
                case 'url':
                    if (!Utils.validateUrl(value)) {
                        this.showError(input, 'Please enter a valid URL');
                        isValid = false;
                    }
                    break;
                case 'number':
                    if (isNaN(value)) {
                        this.showError(input, 'Please enter a valid number');
                        isValid = false;
                    }
                    break;
            }
        }
        
        return isValid;
    },
    
    /**
     * Show error message
     */
    showError(input, message) {
        DOM.addClass(input, 'is-invalid');
        let errorMsg = input.parentElement.querySelector('.invalid-feedback');
        if (!errorMsg) {
            errorMsg = DOM.create('div', 'invalid-feedback');
            input.parentElement.appendChild(errorMsg);
        }
        DOM.setText(errorMsg, message);
        DOM.show(errorMsg);
    },
    
    /**
     * Clear errors
     */
    clearErrors(form) {
        if (typeof form === 'string') {
            form = DOM.select(form);
        }
        const inputs = form.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
            DOM.removeClass(input, 'is-invalid');
            const errorMsg = input.parentElement.querySelector('.invalid-feedback');
            if (errorMsg) {
                DOM.hide(errorMsg);
            }
        });
    },
};

/* ============================================================================
   10. SEARCH & FILTER
   ============================================================================ */

const Search = {
    /**
     * Debounced search handler
     */
    create(inputSelector, onSearch) {
        const input = DOM.select(inputSelector);
        if (input) {
            const debouncedSearch = Utils.debounce((value) => {
                onSearch(value);
            }, 300);
            
            DOM.on(input, 'input', (e) => {
                debouncedSearch(e.target.value);
            });
        }
    },
    
    /**
     * Filter table rows
     */
    filterTable(tableSelector, searchValue) {
        const rows = DOM.selectAll(`${tableSelector} tbody tr`);
        const lowerValue = searchValue.toLowerCase();
        
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            if (text.includes(lowerValue)) {
                DOM.show(row);
            } else {
                DOM.hide(row);
            }
        });
    },
    
    /**
     * Filter array
     */
    filterArray(array, searchValue, searchFields = []) {
        const lowerValue = searchValue.toLowerCase();
        return array.filter(item => {
            return searchFields.some(field => {
                return String(item[field]).toLowerCase().includes(lowerValue);
            });
        });
    },
};

/* ============================================================================
   11. DATE & TIME UTILITIES
   ============================================================================ */

const DateTime = {
    /**
     * Get current date
     */
    now() {
        return new Date();
    },
    
    /**
     * Format date
     */
    format(date, format = 'YYYY-MM-DD') {
        return Utils.formatDate(date, format);
    },
    
    /**
     * Add days
     */
    addDays(date, days) {
        const result = new Date(date);
        result.setDate(result.getDate() + days);
        return result;
    },
    
    /**
     * Subtract days
     */
    subtractDays(date, days) {
        return this.addDays(date, -days);
    },
    
    /**
     * Get days between
     */
    daysBetween(date1, date2) {
        const oneDay = 24 * 60 * 60 * 1000;
        return Math.round(Math.abs((date1 - date2) / oneDay));
    },
    
    /**
     * Is date past
     */
    isPast(date) {
        return new Date(date) < this.now();
    },
    
    /**
     * Is date future
     */
    isFuture(date) {
        return new Date(date) > this.now();
    },
    
    /**
     * Is date today
     */
    isToday(date) {
        const today = this.now();
        const checkDate = new Date(date);
        return checkDate.getDate() === today.getDate() &&
               checkDate.getMonth() === today.getMonth() &&
               checkDate.getFullYear() === today.getFullYear();
    },
};

/* ============================================================================
   12. PAGINATION
   ============================================================================ */

const Pagination = {
    /**
     * Create pagination
     */
    create(currentPage, totalPages, onPageChange) {
        const pagination = DOM.select('.pagination');
        if (!pagination) return;
        
        let html = '<li class="page-item ' + (currentPage === 1 ? 'disabled' : '') + '">';
        html += '<a class="page-link" href="#" data-page="' + (currentPage - 1) + '">← Previous</a></li>';
        
        for (let i = 1; i <= totalPages; i++) {
            html += '<li class="page-item ' + (i === currentPage ? 'active' : '') + '">';
            html += '<a class="page-link" href="#" data-page="' + i + '">' + i + '</a></li>';
        }
        
        html += '<li class="page-item ' + (currentPage === totalPages ? 'disabled' : '') + '">';
        html += '<a class="page-link" href="#" data-page="' + (currentPage + 1) + '">Next →</a></li>';
        
        DOM.setHTML(pagination, html);
        
        // Attach click handlers
        const links = pagination.querySelectorAll('a.page-link');
        links.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = parseInt(link.dataset.page);
                if (page >= 1 && page <= totalPages) {
                    onPageChange(page);
                }
            });
        });
    },
};

/* ============================================================================
   13. CHARTS HELPER
   ============================================================================ */

const Charts = {
    /**
     * Create line chart
     */
    createLineChart(ctx, labels, data, label = 'Data') {
        if (!window.Chart) return;
        
        return new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: label,
                    data: data,
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointBackgroundColor: '#6366f1',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: '#e2e8f0' },
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8' },
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8' },
                    },
                },
            },
        });
    },
    
    /**
     * Create doughnut chart
     */
    createDoughnutChart(ctx, labels, data) {
        if (!window.Chart) return;
        
        const colors = [
            '#6366f1',
            '#8b5cf6',
            '#10b981',
            '#3b82f6',
        ];
        
        return new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors,
                    borderColor: '#1e293b',
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#e2e8f0', padding: 15 },
                    },
                },
            },
        });
    },
    
    /**
     * Create bar chart
     */
    createBarChart(ctx, labels, data, label = 'Data') {
        if (!window.Chart) return;
        
        return new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: label,
                    data: data,
                    backgroundColor: 'rgba(99, 102, 241, 0.8)',
                    borderColor: '#6366f1',
                    borderWidth: 2,
                    borderRadius: 8,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: { color: '#e2e8f0' },
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: '#334155' },
                        ticks: { color: '#94a3b8' },
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8' },
                    },
                },
            },
        });
    },
};

/* ============================================================================
   14. APP INITIALIZATION
   ============================================================================ */

const App = {
    /**
     * Initialize application
     */
    init() {
        TylonERP.log('Initializing TylonERP...');
        
        // Initialize theme
        Theme.init();
        
        // Initialize tooltips
        this.initTooltips();
        
        // Initialize popovers
        this.initPopovers();
        
        // Setup global error handling
        this.setupErrorHandling();
        
        // Setup global AJAX defaults
        this.setupAjax();
        
        // Emit init event
        document.dispatchEvent(new CustomEvent('app:ready'));
        
        TylonERP.log('TylonERP initialized successfully');
    },
    
    /**
     * Initialize Bootstrap tooltips
     */
    initTooltips() {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    },
    
    /**
     * Initialize Bootstrap popovers
     */
    initPopovers() {
        const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
        popoverTriggerList.map(function (popoverTriggerEl) {
            return new bootstrap.Popover(popoverTriggerEl);
        });
    },
    
    /**
     * Setup global error handling
     */
    setupErrorHandling() {
        window.addEventListener('error', (event) => {
            TylonERP.error('Uncaught error:', event.error);
            Notifications.error('An error occurred. Please try again.');
        });
        
        window.addEventListener('unhandledrejection', (event) => {
            TylonERP.error('Unhandled rejection:', event.reason);
            Notifications.error('An error occurred. Please try again.');
        });
    },
    
    /**
     * Setup global AJAX defaults
     */
    setupAjax() {
        if (window.$ && window.$.ajaxSetup) {
            $.ajaxSetup({
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
        }
    },
};

/* ============================================================================
   15. SIDEBAR TOGGLE
   ============================================================================ */

const Sidebar = {
    /**
     * Toggle sidebar
     */
    toggle() {
        const sidebar = DOM.select('.sidebar');
        if (sidebar) {
            DOM.toggleClass(sidebar, 'show');
        }
    },
    
    /**
     * Show sidebar
     */
    show() {
        const sidebar = DOM.select('.sidebar');
        if (sidebar) {
            DOM.addClass(sidebar, 'show');
        }
    },
    
    /**
     * Hide sidebar
     */
    hide() {
        const sidebar = DOM.select('.sidebar');
        if (sidebar) {
            DOM.removeClass(sidebar, 'show');
        }
    },
};

/* ============================================================================
   16. EXPORT DATA
   ============================================================================ */

const Export = {
    /**
     * Export to CSV
     */
    toCSV(data, filename = 'export.csv') {
        let csv = '';
        
        // Headers
        if (data.length > 0) {
            csv += Object.keys(data[0]).join(',') + '\n';
        }
        
        // Data rows
        data.forEach(row => {
            csv += Object.values(row).map(value => {
                if (typeof value === 'string' && value.includes(',')) {
                    return '"' + value + '"';
                }
                return value;
            }).join(',') + '\n';
        });
        
        this.download(csv, filename, 'text/csv');
    },
    
    /**
     * Export to JSON
     */
    toJSON(data, filename = 'export.json') {
        const json = JSON.stringify(data, null, 2);
        this.download(json, filename, 'application/json');
    },
    
    /**
     * Download file
     */
    download(content, filename, type) {
        const blob = new Blob([content], { type: type });
        const url = window.URL.createObjectURL(blob);
        const link = DOM.create('a', '', { href: url, download: filename });
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
    },
};

/* ============================================================================
   17. AUTHENTICATION
   ============================================================================ */

const Auth = {
    /**
     * Check if user is authenticated
     */
    isAuthenticated() {
        return Utils.getStorage('user_token') !== null;
    },
    
    /**
     * Get current user
     */
    getCurrentUser() {
        return Utils.getStorage('current_user', null);
    },
    
    /**
     * Set current user
     */
    setCurrentUser(user) {
        Utils.setStorage('current_user', user);
    },
    
    /**
     * Logout
     */
    logout() {
        Utils.removeStorage('user_token');
        Utils.removeStorage('current_user');
        window.location.href = '/login';
    },
    
    /**
     * Get auth token
     */
    getToken() {
        return Utils.getStorage('user_token', null);
    },
    
    /**
     * Set auth token
     */
    setToken(token) {
        Utils.setStorage('user_token', token);
    },
};

/* ============================================================================
   18. DOCUMENT READY
   ============================================================================ */

document.addEventListener('DOMContentLoaded', function () {
    App.init();
});

/* ============================================================================
   19. EXPORT TO GLOBAL
   ============================================================================ */

// Make utilities available globally
window.TylonERP = TylonERP;
window.Utils = Utils;
window.Notifications = Notifications;
window.API = API;
window.DOM = DOM;
window.Modals = Modals;
window.Tables = Tables;
window.Theme = Theme;
window.FormValidator = FormValidator;
window.Search = Search;
window.DateTime = DateTime;
window.Pagination = Pagination;
window.Charts = Charts;
window.App = App;
window.Sidebar = Sidebar;
window.Export = Export;
window.Auth = Auth;
