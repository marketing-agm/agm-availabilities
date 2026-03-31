// POST /api/auth
// Handles agent login and initial password setup
// Body: { property: string, password: string, action?: "login" | "setup" }

import { handleOptions, jsonResponse, errorResponse, sha256, generateToken, generateSalt } from './_utils.js';

export async function onRequestOptions() {
    return handleOptions();
}

export async function onRequestPost(context) {
    const { request, env } = context;
    const db = env.DB;

    try {
        const body = await request.json();
        const { property, password, action } = body;

        if (!property || !password) {
            return errorResponse('Property and password are required.');
        }

        if (password.length < 6) {
            return errorResponse('Password must be at least 6 characters.');
        }

        // Check if property already has a password
        const existing = await db.prepare(
            'SELECT id, password_hash, salt FROM property_auth WHERE property = ?'
        ).bind(property).first();

        if (action === 'setup') {
            // Initial password setup (only if no password exists yet)
            if (existing) {
                return errorResponse('Password already set for this property. Use login instead.', 409);
            }

            const salt = generateSalt();
            const hash = await sha256(salt + password);

            await db.prepare(
                'INSERT INTO property_auth (property, password_hash, salt) VALUES (?, ?, ?)'
            ).bind(property, hash, salt).run();

            // Auto-login after setup
            const token = generateToken();
            const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(); // 24 hours

            await db.prepare(
                'INSERT INTO sessions (token, property, expires_at) VALUES (?, ?, ?)'
            ).bind(token, property, expiresAt).run();

            return jsonResponse({
                success: true,
                message: 'Password set successfully.',
                token,
                property,
                expires_at: expiresAt,
            });
        }

        // Default action: login
        if (!existing) {
            return errorResponse('No password set for this property. Please set up a password first.', 404);
        }

        const hash = await sha256(existing.salt + password);

        if (hash !== existing.password_hash) {
            return errorResponse('Incorrect password.', 401);
        }

        // Create session token (24 hour expiry)
        const token = generateToken();
        const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

        await db.prepare(
            'INSERT INTO sessions (token, property, expires_at) VALUES (?, ?, ?)'
        ).bind(token, property, expiresAt).run();

        return jsonResponse({
            success: true,
            token,
            property,
            expires_at: expiresAt,
        });

    } catch (err) {
        console.error('Auth error:', err);
        return errorResponse('Internal server error.', 500);
    }
}

// GET /api/auth/check - verify if a property has a password set
export async function onRequestGet(context) {
    const { request, env } = context;
    const db = env.DB;
    const url = new URL(request.url);
    const property = url.searchParams.get('property');

    if (!property) {
        return errorResponse('Property parameter is required.');
    }

    try {
        const existing = await db.prepare(
            'SELECT id FROM property_auth WHERE property = ?'
        ).bind(property).first();

        return jsonResponse({
            property,
            has_password: !!existing,
        });
    } catch (err) {
        console.error('Auth check error:', err);
        return errorResponse('Internal server error.', 500);
    }
}
