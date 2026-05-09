// /api/slots
// GET  - Public: fetch available slots for a property + date range
// POST - Auth required: create new availability slot(s)
// DELETE - Auth required: remove a slot by ID

import { handleOptions, jsonResponse, errorResponse, validateSession, isAdmin } from './_utils.js';

export async function onRequestOptions() {
    return handleOptions();
}

// GET /api/slots?property=X&from=YYYY-MM-DD&to=YYYY-MM-DD
// Public endpoint — prospects use this to see available times
export async function onRequestGet(context) {
    const { request, env } = context;
    const db = env.DB;
    const url = new URL(request.url);

    const property = url.searchParams.get('property');
    const from = url.searchParams.get('from');
    const to = url.searchParams.get('to');

    if (!property) {
        return errorResponse('Property parameter is required.');
    }

    try {
        let query;
        let params;

        if (from && to) {
            query = `
                SELECT s.id, s.property, s.slot_date, s.start_time, s.end_time, s.status,
                       b.first_name AS booked_by_first, b.last_name AS booked_by_last,
                       b.email AS booked_by_email, b.phone AS booked_by_phone,
                       b.booked_at
                FROM slots s
                LEFT JOIN bookings b ON s.id = b.slot_id
                WHERE s.property = ? AND s.slot_date >= ? AND s.slot_date <= ?
                ORDER BY s.slot_date ASC, s.start_time ASC
            `;
            params = [property, from, to];
        } else if (from) {
            query = `
                SELECT s.id, s.property, s.slot_date, s.start_time, s.end_time, s.status,
                       b.first_name AS booked_by_first, b.last_name AS booked_by_last,
                       b.email AS booked_by_email, b.phone AS booked_by_phone,
                       b.booked_at
                FROM slots s
                LEFT JOIN bookings b ON s.id = b.slot_id
                WHERE s.property = ? AND s.slot_date >= ?
                ORDER BY s.slot_date ASC, s.start_time ASC
            `;
            params = [property, from];
        } else {
            query = `
                SELECT s.id, s.property, s.slot_date, s.start_time, s.end_time, s.status,
                       b.first_name AS booked_by_first, b.last_name AS booked_by_last,
                       b.email AS booked_by_email, b.phone AS booked_by_phone,
                       b.booked_at
                FROM slots s
                LEFT JOIN bookings b ON s.id = b.slot_id
                WHERE s.property = ? AND s.slot_date >= date('now')
                ORDER BY s.slot_date ASC, s.start_time ASC
            `;
            params = [property];
        }

        const stmt = db.prepare(query);
        const result = await stmt.bind(...params).all();

        // Check if request is from an authenticated agent or admin
        const authedProperty = await validateSession(request, db);
        const isAgentOrAdmin = isAdmin(authedProperty) || authedProperty === property;

        // For prospects (unauthenticated), strip booking contact details
        const slots = result.results.map(slot => {
            const base = {
                id: slot.id,
                property: slot.property,
                date: slot.slot_date,
                start_time: slot.start_time,
                end_time: slot.end_time,
                status: slot.status,
            };

            // Agents/admins see full booking details; prospects just see status
            if (isAgentOrAdmin && slot.booked_by_first) {
                base.booking = {
                    first_name: slot.booked_by_first,
                    last_name: slot.booked_by_last,
                    email: slot.booked_by_email,
                    phone: slot.booked_by_phone,
                    booked_at: slot.booked_at,
                };
            }

            return base;
        });

        return jsonResponse({ property, slots });

    } catch (err) {
        console.error('Slots GET error:', err);
        return errorResponse('Internal server error.', 500);
    }
}

// POST /api/slots
// Auth required. Creates one or more availability slots.
// Body: { property?: string, slots: [{ date, start_time, end_time }] }
//   Admin must pass property in the body. Per-property agents use their session property.
export async function onRequestPost(context) {
    const { request, env } = context;
    const db = env.DB;

    const authedProperty = await validateSession(request, db);
    if (!authedProperty) {
        return errorResponse('Authentication required. Please log in.', 401);
    }

    try {
        const body = await request.json();

        // Determine which property to create slots for
        let property;
        if (isAdmin(authedProperty)) {
            // Admin must specify which property
            property = body.property;
            if (!property) {
                return errorResponse('Admin must specify a property.');
            }
        } else {
            // Per-property agent uses their session property
            property = authedProperty;
        }

        // Normalize to array
        const slotsInput = body.slots || [body];

        const errors = [];
        const validSlots = [];

        for (let i = 0; i < slotsInput.length; i++) {
            const s = slotsInput[i];
            const idx = slotsInput.length > 1 ? ` (slot ${i + 1})` : '';

            if (!s.date || !s.start_time || !s.end_time) {
                errors.push(`Missing date, start_time, or end_time${idx}.`);
                continue;
            }

            if (!/^\d{4}-\d{2}-\d{2}$/.test(s.date)) {
                errors.push(`Invalid date format${idx}. Use YYYY-MM-DD.`);
                continue;
            }

            if (!/^\d{2}:\d{2}$/.test(s.start_time) || !/^\d{2}:\d{2}$/.test(s.end_time)) {
                errors.push(`Invalid time format${idx}. Use HH:MM (24-hour).`);
                continue;
            }

            if (s.end_time <= s.start_time) {
                errors.push(`End time must be after start time${idx}.`);
                continue;
            }

            const slotDate = new Date(s.date + 'T00:00:00Z');
            const today = new Date();
            today.setUTCHours(0, 0, 0, 0);
            if (slotDate < today) {
                errors.push(`Cannot create slots in the past${idx}.`);
                continue;
            }

            const overlap = await db.prepare(`
                SELECT id FROM slots
                WHERE property = ? AND slot_date = ?
                AND start_time < ? AND end_time > ?
                AND status = 'available'
            `).bind(property, s.date, s.end_time, s.start_time).first();

            if (overlap) {
                errors.push(`Overlaps with existing slot${idx} on ${s.date}.`);
                continue;
            }

            validSlots.push(s);
        }

        if (validSlots.length === 0) {
            return errorResponse(errors.join(' '), 400);
        }

        const inserted = [];
        for (const s of validSlots) {
            const result = await db.prepare(
                'INSERT INTO slots (property, slot_date, start_time, end_time) VALUES (?, ?, ?, ?)'
            ).bind(property, s.date, s.start_time, s.end_time).run();

            inserted.push({
                id: result.meta.last_row_id,
                property,
                date: s.date,
                start_time: s.start_time,
                end_time: s.end_time,
                status: 'available',
            });
        }

        const response = {
            success: true,
            created: inserted.length,
            slots: inserted,
        };

        if (errors.length > 0) {
            response.warnings = errors;
        }

        return jsonResponse(response, 201);

    } catch (err) {
        console.error('Slots POST error:', err);
        return errorResponse('Internal server error.', 500);
    }
}

// DELETE /api/slots?id=X
// Auth required. Deletes an available slot (cannot delete booked slots).
export async function onRequestDelete(context) {
    const { request, env } = context;
    const db = env.DB;

    const authedProperty = await validateSession(request, db);
    if (!authedProperty) {
        return errorResponse('Authentication required. Please log in.', 401);
    }

    const url = new URL(request.url);
    const slotId = url.searchParams.get('id');

    if (!slotId) {
        return errorResponse('Slot ID is required.');
    }

    try {
        const slot = await db.prepare(
            'SELECT id, property, status FROM slots WHERE id = ?'
        ).bind(slotId).first();

        if (!slot) {
            return errorResponse('Slot not found.', 404);
        }

        // Admin can delete any property's slots; per-property agents only their own
        if (!isAdmin(authedProperty) && slot.property !== authedProperty) {
            return errorResponse('You can only delete slots for your own property.', 403);
        }

        if (slot.status === 'booked') {
            return errorResponse('Cannot delete a booked slot. Cancel the booking first.', 409);
        }

        await db.prepare('DELETE FROM slots WHERE id = ?').bind(slotId).run();

        return jsonResponse({ success: true, deleted_id: parseInt(slotId) });

    } catch (err) {
        console.error('Slots DELETE error:', err);
        return errorResponse('Internal server error.', 500);
    }
}
