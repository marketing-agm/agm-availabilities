// Shared utilities for AGM Tour API
// Used by all Pages Functions endpoints

// CORS headers for cross-origin requests (iframe embeds)
export const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Content-Type': 'application/json',
};

// Handle CORS preflight
export function handleOptions() {
    return new Response(null, { status: 204, headers: corsHeaders });
}

// JSON response helper
export function jsonResponse(data, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: corsHeaders,
    });
}

// Error response helper
export function errorResponse(message, status = 400) {
    return new Response(JSON.stringify({ error: message }), {
        status,
        headers: corsHeaders,
    });
}

// SHA-256 hash helper using Web Crypto API (available in Workers)
export async function sha256(message) {
    const msgBuffer = new TextEncoder().encode(message);
    const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

// Generate a random token for sessions
export function generateToken() {
    const array = new Uint8Array(32);
    crypto.getRandomValues(array);
    return Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
}

// Generate a random salt for password hashing
export function generateSalt() {
    const array = new Uint8Array(16);
    crypto.getRandomValues(array);
    return Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
}

// Validate session token from Authorization header
// Returns the property name if valid, null if not
export async function validateSession(request, db) {
    const authHeader = request.headers.get('Authorization');
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
        return null;
    }

    const token = authHeader.slice(7);

    // Clean up expired sessions opportunistically
    await db.prepare(
        "DELETE FROM sessions WHERE expires_at < datetime('now')"
    ).run();

    // Check if token exists and is valid
    const session = await db.prepare(
        "SELECT property FROM sessions WHERE token = ? AND expires_at > datetime('now')"
    ).bind(token).first();

    return session ? session.property : null;
}
