from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import Booking, User, Facility, Notification
from functools import wraps

admin = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


@admin.route('/admin/requests')
@login_required
@admin_required
def manage_requests():
    status_filter = request.args.get('status', 'pending')
    query = Booking.query
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    all_bookings = query.order_by(Booking.created_at.desc()).all()
    return render_template('admin/manage_requests.html',
        bookings=all_bookings, status_filter=status_filter)


@admin.route('/admin/requests/<int:booking_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_booking(booking_id):
    booking     = Booking.query.get_or_404(booking_id)
    admin_notes = request.form.get('admin_notes', '').strip()

    # Final conflict check before approving
    conflicts = Booking.check_conflict(
        booking.facility_id, booking.booking_date,
        booking.start_time,  booking.end_time,
        exclude_id=booking.id)
    if conflicts:
        flash('Cannot approve: conflict with an existing approved booking.', 'danger')
        return redirect(url_for('admin.manage_requests'))

    booking.status      = 'approved'
    booking.admin_notes = admin_notes
    db.session.add(Notification(
        user_id    = booking.user_id,
        message    = f'Your booking "{booking.title}" for {booking.facility.name} '
                     f'on {booking.booking_date} has been APPROVED.',
        type       = 'success',
        booking_id = booking.id,
    ))
    db.session.commit()
    flash(f'Booking "{booking.title}" approved.', 'success')
    return redirect(url_for('admin.manage_requests'))


@admin.route('/admin/requests/<int:booking_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_booking(booking_id):
    booking     = Booking.query.get_or_404(booking_id)
    admin_notes = request.form.get('admin_notes', '').strip()

    booking.status      = 'rejected'
    booking.admin_notes = admin_notes or 'Request rejected by administrator.'
    db.session.add(Notification(
        user_id    = booking.user_id,
        message    = f'Your booking "{booking.title}" for {booking.facility.name} '
                     f'on {booking.booking_date} has been REJECTED. '
                     f'Reason: {booking.admin_notes}',
        type       = 'danger',
        booking_id = booking.id,
    ))
    db.session.commit()
    flash(f'Booking "{booking.title}" rejected.', 'info')
    return redirect(url_for('admin.manage_requests'))


@admin.route('/admin/users')
@login_required
@admin_required
def manage_users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/manage_users.html', users=all_users)


@admin.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.manage_users'))
    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User {user.full_name} {status}.', 'success')
    return redirect(url_for('admin.manage_users'))

# Payment Orders for external bookings
@admin.route('/admin/payments')
@login_required
@admin_required
def payment_orders_list():
    from models import PaymentOrder
    status_filter = request.args.get('status', 'all')
    query = PaymentOrder.query
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    orders = query.order_by(PaymentOrder.created_at.desc()).all()

    stats = {
        'total':   PaymentOrder.query.count(),
        'paid':    PaymentOrder.query.filter_by(status='paid').count(),
        'pending': PaymentOrder.query.filter_by(status='pending').count(),
        'other':   PaymentOrder.query.filter(
                       PaymentOrder.status.in_(['cancelled', 'failed'])).count(),
    }
    return render_template('admin/payment_orders.html',
        orders=orders, stats=stats, status_filter=status_filter)


@admin.route('/admin/payments/<int:order_id>')
@login_required
@admin_required
def payment_order_detail(order_id):
    from models import PaymentOrder
    order = PaymentOrder.query.get_or_404(order_id)
    return render_template('admin/payment_order_detail.html', order=order)


# Attendance Dashboard 
@admin.route('/admin/attendance')
@login_required
@admin_required
def attendance():
    from models import Booking
    from datetime import date, timedelta

    view  = request.args.get('view', 'today')
    today = date.today()

    if view == 'today':
        bookings     = Booking.query.filter(
            Booking.booking_date == today,
            Booking.status.in_(['approved', 'paid'])
        ).order_by(Booking.start_time).all()
        period_label = f"Today — {today.strftime('%d %b %Y')}"

    elif view == 'week':
        bookings = Booking.query.filter(
            Booking.booking_date >= today,
            Booking.booking_date <= today + timedelta(days=7),
            Booking.status.in_(['approved', 'paid'])
        ).order_by(Booking.booking_date, Booking.start_time).all()
        period_label = "Next 7 Days"

    else:  
        bookings = Booking.query.filter(
            Booking.status.in_(['approved', 'paid'])
        ).order_by(Booking.booking_date.desc(), Booking.start_time.desc()).limit(100).all()
        period_label = "All Time (last 100)"

    attended = [b for b in bookings if b.is_attended]
    no_show  = [b for b in bookings if not b.is_attended and b.booking_date < today]
    upcoming = [b for b in bookings if not b.is_attended and b.booking_date >= today]
    rate     = round(len(attended) / len(bookings) * 100, 1) if bookings else 0

    return render_template('admin/attendance.html',
        bookings=bookings, attended=attended, no_show=no_show,
        upcoming=upcoming, attendance_rate=rate,
        view=view, period_label=period_label, today=today)
