// /api/book
// POST — public, prospects book an available slot
// DELETE — auth required, cancel a booking

import { handleOptions, jsonResponse, errorResponse, validateSession, isAdmin } from './_utils.js';

export async function onRequestOptions() {
    return handleOptions();
}

export async function onRequestPost(context) {
    const { request, env } = context;
    const db = env.DB;

    try {
        const body = await request.json();
        const {
            slot_id,
            first_name,
            last_name = '',
            email,
            phone,
            move_in_date = '',
            unit_types = '',
            notes = '',
        } = body;

        if (!slot_id || !first_name || !email || !phone) {
            return errorResponse('slot_id, first_name, email, and phone are required.');
        }

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            return errorResponse('Invalid email address.');
        }

        const slot = await db.prepare(
            'SELECT id, property, slot_date, start_time, end_time, status FROM slots WHERE id = ?'
        ).bind(slot_id).first();

        if (!slot) {
            return errorResponse('Slot not found.', 404);
        }

        if (slot.status === 'booked') {
            return errorResponse('This time slot has already been booked. Please choose another.', 409);
        }

        const slotDateTime = new Date(slot.slot_date + 'T' + slot.start_time + ':00');
        if (slotDateTime < new Date()) {
            return errorResponse('This time slot has already passed.', 410);
        }

        const statements = [
            db.prepare(
                "UPDATE slots SET status = 'booked', updated_at = datetime('now') WHERE id = ? AND status = 'available'"
            ).bind(slot_id),
            db.prepare(
                'INSERT INTO bookings (slot_id, property, first_name, last_name, email, phone, move_in_date, unit_types, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
            ).bind(slot_id, slot.property, first_name, last_name, email, phone, move_in_date, unit_types, notes),
        ];

        const results = await db.batch(statements);

        if (results[0].meta.changes === 0) {
            return errorResponse('This time slot was just booked by someone else. Please choose another.', 409);
        }

        const formatDate = (dateStr) => {
            const d = new Date(dateStr + 'T00:00:00');
            return d.toLocaleDateString('en-US', {
                weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
            });
        };

        const formatTime = (timeStr) => {
            const [h, m] = timeStr.split(':').map(Number);
            const ampm = h >= 12 ? 'PM' : 'AM';
            const hour12 = h % 12 || 12;
            return `${hour12}:${m.toString().padStart(2, '0')} ${ampm}`;
        };

        return jsonResponse({
            success: true,
            booking: {
                slot_id: slot.id,
                property: slot.property,
                date: slot.slot_date,
                date_formatted: formatDate(slot.slot_date),
                start_time: slot.start_time,
                end_time: slot.end_time,
                time_formatted: `${formatTime(slot.start_time)} - ${formatTime(slot.end_time)}`,
                prospect: {
                    first_name, last_name, email, phone, move_in_date, unit_types, notes,
                },
            },
        }, 201);

    } catch (err) {
        console.error('Booking error:', err);

        if (err.message && err.message.includes('UNIQUE constraint failed')) {
            return errorResponse('This time slot has already been booked.', 409);
        }

        return errorResponse('Internal server error.', 500);
    }
}

// DELETE /api/book?id=X or DELETE /api/book?slot_id=X
// Auth required — admin or per-property agent can cancel a booking
export async function onRequestDelete(context) {
    const { request, env } = context;
    const db = env.DB;

    const authedProperty = await validateSession(request, db);
    if (!authedProperty) {
        return errorResponse('Authentication required.', 401);
    }

    const url = new URL(request.url);
    const bookingId = url.searchParams.get('id');
    const slotId = url.searchParams.get('slot_id');

    if (!bookingId && !slotId) {
        return errorResponse('Booking ID or slot_id is required.');
    }

    try {
        let booking;

        if (slotId) {
            booking = await db.prepare(
                'SELECT id, slot_id, property FROM bookings WHERE slot_id = ?'
            ).bind(slotId).first();
        } else {
            booking = await db.prepare(
                'SELECT id, slot_id, property FROM bookings WHERE id = ?'
            ).bind(bookingId).first();
        }

        if (!booking) {
            return errorResponse('Booking not found.', 404);
        }

        // Admin can cancel any booking; per-property agents only their own
        if (!isAdmin(authedProperty) && booking.property !== authedProperty) {
            return errorResponse('You can only cancel bookings for your own property.', 403);
        }

        // Delete booking and reset slot to available
        await db.batch([
            db.prepare('DELETE FROM bookings WHERE id = ?').bind(booking.id),
            db.prepare(
                "UPDATE slots SET status = 'available', updated_at = datetime('now') WHERE id = ?"
            ).bind(booking.slot_id),
        ]);

        return jsonResponse({
            success: true,
            cancelled_booking_id: booking.id,
            freed_slot_id: booking.slot_id,
        });

    } catch (err) {
        console.error('Cancel booking error:', err);
        return errorResponse('Internal server error.', 500);
    }
}
