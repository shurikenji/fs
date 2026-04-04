// ==================== DOM ELEMENTS ====================
const form = document.getElementById('checkForm');
const serverSelect = document.getElementById('server');
const apiKeyInput = document.getElementById('apiKey');
const toggleBtn = document.getElementById('toggleKey');
const submitBtn = document.getElementById('submitBtn');
const resultBox = document.getElementById('result');
const errorBox = document.getElementById('error');

// ==================== INITIALIZE ====================
document.addEventListener('DOMContentLoaded', loadServers);

async function loadServers() {
    try {
        const response = await fetch('/api/servers');
        const data = await response.json();

        serverSelect.innerHTML = '<option value="">Select server</option>';

        data.servers.forEach(s => {
            const option = document.createElement('option');
            option.value = s.id;
            option.textContent = s.name;
            serverSelect.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load servers:', error);
        serverSelect.innerHTML = '<option value="">Error loading servers</option>';
    }
}

// ==================== TOGGLE PASSWORD ====================
toggleBtn.addEventListener('click', () => {
    const isPassword = apiKeyInput.type === 'password';
    apiKeyInput.type = isPassword ? 'text' : 'password';
    toggleBtn.setAttribute('aria-label', isPassword ? 'Hide key' : 'Show key');
});

// ==================== FORM SUBMIT ====================
form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const apiKey = apiKeyInput.value.trim();
    const server = serverSelect.value;

    // Validation
    if (!server) {
        showError('Please select a server');
        return;
    }

    if (!apiKey || !apiKey.startsWith('sk-')) {
        showError('Invalid API key format. Must start with sk-');
        return;
    }

    // Start loading
    setLoading(true);
    hideError();
    hideResult();

    try {
        const response = await fetch('/api/check-balance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: apiKey, server }),
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to check balance');
        }

        showResult(data);
    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
    }
});

// ==================== UI HELPERS ====================
function setLoading(loading) {
    submitBtn.disabled = loading;
    submitBtn.classList.toggle('loading', loading);
}

function showResult(data) {
    const { server, data: balanceData } = data;

    // Update values
    document.querySelector('.result-server').textContent = server;
    document.querySelector('.balance-value').textContent = `$${balanceData.balance_usd}`;
    document.querySelector('.usage-value').textContent = `$${balanceData.usage_usd}`;
    document.querySelector('.limit-value').textContent = `$${balanceData.limit_usd}`;

    // Calculate percentage
    const limit = parseFloat(balanceData.limit_usd);
    const usage = parseFloat(balanceData.usage_usd);
    const percentage = limit > 0 ? Math.min(100, (usage / limit) * 100) : 0;

    document.querySelector('.progress-fill').style.width = `${percentage}%`;
    document.querySelector('.progress-text').textContent = `${percentage.toFixed(1)}% used`;

    // Show
    resultBox.classList.remove('hidden');
}

function hideResult() {
    resultBox.classList.add('hidden');
}

function showError(message) {
    document.querySelector('.error-message').textContent = message;
    errorBox.classList.remove('hidden');
}

function hideError() {
    errorBox.classList.add('hidden');
}
