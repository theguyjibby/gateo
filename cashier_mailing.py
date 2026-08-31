import logging
from flask_mail import Message
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from extensions import mail

logger = logging.getLogger(__name__)


def send_withdrawal_link(
    organizer_email,
    event_name,
    organizer_id,
    event_id,
    base_url,
    token,
):
    try:
        msg = Message(
            subject=f"initiated a Withdrawal on Gateo",
            recipients=[organizer_email],
        )

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto;">
            <h2>{event_name}</h2>
            <p>To continue with your withdrawal click the link below</p>
            <p>{base_url}cashier/withdrawal/{organizer_id}/{event_id}?token={token}</p>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Organizer Notification Email Error:", e)
        return False


def send_cancellation_link(
    organizer_email,
    event_name,
    cancel_token,
    base_url,
):
    try:
        msg = Message(
            subject=f"Cancellation Request - {event_name}",
            recipients=[organizer_email],
        )

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto;">
            <h2>{event_name}</h2>
            <p>You have requested to cancel this event.</p>
            <p>To confirm and complete the cancellation, click the link below.</p>
            <p><a href="{base_url}cashier/cancel?token={cancel_token}" style="background-color:#dc2626; color:white; padding:12px 24px; text-decoration:none; border-radius:8px; font-weight:bold;">Review and Cancel Event</a></p>
            <p style="color:#6b7280; font-size:12px;">If you did not request this, you can safely ignore this email.</p>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Cancellation Link Email Error:", e)
        return False


def send_withdrawal_success_email(
    organizer_email,
    event_name,
    amount,
    account_name,
    bank_name,
    account_number,
):
    try:
        msg = Message(
            subject=f"Withdrawal Successful - {event_name}",
            recipients=[organizer_email],
        )

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto;">
            <h2>Withdrawal Successful</h2>
            <p>Your withdrawal for <strong>{event_name}</strong> has been processed successfully.</p>
            <div style="background: #f8fafc; border-radius: 8px; padding: 16px; margin: 16px 0;">
                <p><strong>Amount:</strong> ₦{amount:,.0f}</p>
                <p><strong>Account Name:</strong> {account_name}</p>
                <p><strong>Bank:</strong> {bank_name}</p>
                <p><strong>Account Number:</strong> {account_number}</p>
            </div>
            <p>The funds should arrive in your account shortly.</p>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Withdrawal Success Email Error:", e)
        return False