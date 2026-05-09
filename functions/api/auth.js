// /api/auth
// POST — admin login or first-time password setup
// GET  — check if admin password has been set up

import { handleOptions, jsonResponse, errorResponse, sha256, generateToken, generateSalt } from './_utils.js';

export async function onRequestOptions() {
    return handleOptions();
}

export async function onRequestPost(context) {
    const { request, env } = context;
    const db = env.DB;

    try {
        const body = await request.json();
        const { password, action, property } = body;

        // ── ADMIN AUTH (new default) ──
        if (!property) {
            if (!password) {
                return errorResponse('Password is required.');
            }

            if (password.length < 6) {
                return errorResponse('Password must be at least 6 characters.');
            }

            // Check if admin password exists
            const existing = await db.prepare(
                'SELECT id, password_hash, salt FROM admin_auth LIMIT 1'
            ).first();

            if (action === 'setup') {
                if (existing) {
                    return errorResponse('Admin password already set. Use login instead.', 409);
                }

                const salt = generateSalt();
                const hash = await sha256(salt + password);

                await db.prepare(
                    'INSERT INTO admin_auth (password_hash, salt) VALUES (?, ?)'
                ).bind(hash, salt).run();

                // Auto-login after setup
                const token = generateToken();
                const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

                await db.prepare(
                    'INSERT INTO sessions (token, property, expires_at) VALUES (?, ?, ?)'
                ).bind(token, '__admin__', expiresAt).run();

                return jsonResponse({
                    success: true,
                    message: 'Admin password set successfully.',
                    token,
                    admin: true,
                    expires_at: expiresAt,
                });
            }

            // Default: admin login
            if (!existing) {
                return errorResponse('No admin password set. Please set up a password first.', 404);
            }

            const hash = await sha256(existing.salt + password);

            if (hash !== existing.password_hash) {
                return errorResponse('Incorrect password.', 401);
            }

            const token = generateToken();
            const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

            await db.prepare(
                'INSERT INTO sessions (token, property, expires_at) VALUES (?, ?, ?)'
            ).bind(token, '__admin__', expiresAt).run();

            return jsonResponse({
                success: true,
                token,
                admin: true,
                expires_at: expiresAt,
            });
        }

        // ── LEGACY PER-PROPERTY AUTH (fallback, kept for backward compat) ──
        if (!password) {
            return errorResponse('Property and password are required.');
        }

        if (password.length < 6) {
            return errorResponse('Password must be at least 6 characters.');
        }

        const existing = await db.prepare(
            'SELECT id, password_hash, salt FROM property_auth WHERE property = ?'
        ).bind(property).first();

        if (action === 'setup') {
            if (existing) {
                return errorResponse('Password already set for this property. Use login instead.', 409);
            }

            const salt = generateSalt();
            const hash = await sha256(salt + password);

            await db.prepare(
                'INSERT INTO property_auth (property, password_hash, salt) VALUES (?, ?, ?)'
            ).bind(property, hash, salt).run();

            const token = generateToken();
            const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();

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

        if (!existing) {
            return errorResponse('No password set for this property.', 404);
        }

        const hash = await sha256(existing.salt + password);

        if (hash !== existing.password_hash) {
            return errorResponse('Incorrect password.', 401);
        }

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

// GET /api/auth — check if admin password is set up
// GET /api/auth?property=X — check if a specific property has a password (legacy)
export async function onRequestGet(context) {
    const { request, env } = context;
    const db = env.DB;
    const url = new URL(request.url);
    const property = url.searchParams.get('property');

    try {
        if (!property) {
            // Check admin password
            const existing = await db.prepare(
                'SELECT id FROM admin_auth LIMIT 1'
            ).first();

            return jsonResponse({
                admin: true,
                has_password: !!existing,
            });
        }

        // Legacy: check per-property password
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
