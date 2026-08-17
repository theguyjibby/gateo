import base64

from flask_mail import Message
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from extensions import mail


def send_email(to_email, qr_base64, event_name, ticket_name, ticket_type):
    message = Mail(
        from_email='your@email.com',
        to_emails=to_email,
        subject='Your Ticket',
        html_content=f"""
        <h2>Your Ticket for {event_name}</h2>
        <p><strong>Ticket Name:</strong> {ticket_name}</p>
        <p><strong>Ticket Type:</strong> {ticket_type}</p>
        <p>Scan this QR code at the entrance:</p>
        <img src="data:image/png;base64,{qr_base64}">
        """
    )
    sg = SendGridAPIClient("YOUR_API_KEY")
    sg.send(message)


def send_ticket_email_flask(to_email, qr_base64=None, event_name=None, ticket_name=None, ticket_type=None, tickets=None):
    try:
        if tickets is None:
            tickets = [{
                'qr_base64': qr_base64,
                'ticket_name': ticket_name,
                'ticket_type': ticket_type
            }]

        ticket_count = len(tickets)
        msg = Message(
            subject=f"Your {'Tickets' if ticket_count != 1 else 'Ticket'} for {event_name}",
            recipients=[to_email]
        )

        ticket_blocks = []
        for index, ticket in enumerate(tickets, start=1):
            ticket_code = ticket.get('ticket_code', '')
            ticket_blocks.append(f"""
            <div style="background-color:#ffffff; border:1px solid #e5e7eb; border-radius:12px; padding:18px; margin:16px 0; text-align:center;">
                <p style="font-size:13px; color:#64748b; font-weight:bold; margin:0 0 6px;">Ticket {index} of {ticket_count}</p>
                <h3 style="font-size:18px; margin:0 0 8px;">{ticket['ticket_type']}</h3>
                <p style="font-size:14px; margin:0 0 14px;"><strong>Name:</strong> {ticket['ticket_name']}</p>
                <img src="cid:qrcode{index}" alt="Ticket QR Code {index}" style="width:210px; height:210px; display:block; margin:0 auto;" />
                {"<p style='font-size:14px; margin:10px 0 0; font-family:monospace; letter-spacing:1px;'><strong>Ticket ID:</strong> {0}</p>".format(ticket_code) if ticket_code else ''}
                <p style="font-size:11px; color:#64748b; font-weight:bold; margin-top:12px; text-transform:uppercase; letter-spacing:1px;">Scan at entrance</p>
            </div>
            """)

        plural_ticket = 'tickets' if ticket_count != 1 else 'ticket'
        plural_have = 'have' if ticket_count != 1 else 'has'
        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto;">
            <h2 style="text-align:center; margin-bottom:8px;">{event_name}</h2>
            <p style="text-align:center; font-size:15px; color:#374151; margin-bottom:20px;">
                Your {ticket_count} {plural_ticket} {plural_have} been created successfully.
            </p>
            {''.join(ticket_blocks)}
            <p style="text-align:center; color:#555; font-size:12px; margin-top:24px;">Powered by Gateo</p>
        </div>
        """

        for index, ticket in enumerate(tickets, start=1):
            qr_bytes = base64.b64decode(ticket['qr_base64'])
            msg.attach(
                f"ticket-{index}-qrcode.png",
                "image/png",
                qr_bytes,
                headers={'Content-ID': f'<qrcode{index}>'},
                disposition="inline"
            )

        mail.send(msg)
        return True

    except Exception as e:
        print("Organizer Notification Email Error:", e)
        return False


def send_date_location_change_notification(to_email, event_name, old_date, new_date, old_location, new_location, refund_deadline, event_slug):
    try:
        msg = Message(
            subject=f"Update for {event_name} - Action may be required",
            recipients=[to_email]
        )

        changes = []
        if old_date != new_date:
            changes.append(f"""
                <tr>
                    <td style="padding:8px 12px; font-weight:bold; color:#374151; border-bottom:1px solid #e5e7eb;">Date</td>
                    <td style="padding:8px 12px; color:#6b7280; border-bottom:1px solid #e5e7eb; text-decoration:line-through;">{old_date}</td>
                    <td style="padding:8px 12px; color:#059669; font-weight:bold; border-bottom:1px solid #e5e7eb;">{new_date}</td>
                </tr>
                """)
        if old_location != new_location:
            changes.append(f"""
                <tr>
                    <td style="padding:8px 12px; font-weight:bold; color:#374151; border-bottom:1px solid #e5e7eb;">Location</td>
                    <td style="padding:8px 12px; color:#6b7280; border-bottom:1px solid #e5e7eb; text-decoration:line-through;">{old_location}</td>
                    <td style="padding:8px 12px; color:#059669; font-weight:bold; border-bottom:1px solid #e5e7eb;">{new_location}</td>
                </tr>
                """)

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto;">
            <h2 style="text-align:center; margin-bottom:8px;">{event_name}</h2>
            <p style="text-align:center; font-size:15px; color:#374151; margin-bottom:20px;">
                The organizer has updated the event details.
            </p>
            <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
                {''.join(changes)}
            </table>
            <div style="background:#fef3c7; border:1px solid #f59e0b; border-radius:8px; padding:16px; margin-bottom:20px;">
                <p style="margin:0 0 8px; font-weight:bold; color:#92400e;">Request a Refund</p>
                <p style="margin:0; font-size:14px; color:#92400e;">
                    If these changes don't work for you, you can request a full refund before <strong>{refund_deadline}</strong>.
                </p>
            </div>
            <div style="text-align:center; margin:24px 0;">
                <a href="https://gateo.co/event/{event_slug}/request-refund" style="background-color:#7c3aed; color:white; padding:12px 24px; text-decoration:none; border-radius:8px; font-weight:bold;">Request Refund</a>
            </div>
            <p style="text-align:center; color:#555; font-size:12px; margin-top:24px;">Powered by Gateo</p>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Date/Location Change Notification Error:", e)
        return False


def send_event_cancelled_notification(to_email, event_name):
    try:
        msg = Message(
            subject=f"Event Cancelled: {event_name}",
            recipients=[to_email]
        )

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto;">
            <h2 style="text-align:center; margin-bottom:8px;">{event_name}</h2>
            <p style="text-align:center; font-size:15px; color:#374151; margin-bottom:20px;">
                This event has been cancelled by the organizer.
            </p>
            <div style="background:#fef2f2; border:1px solid #fecaca; padding:15px; border-radius:8px; margin-bottom:20px;">
                <p style="margin:0; font-size:14px; color:#991b1b;">
                    A refund of 94% of your ticket price (minus a 6% processing fee) has been initiated.
                    The refund will be processed automatically.
                </p>
            </div>
            <p style="color:#6b7280; font-size:14px;">If you already have a refund request in progress, no further action is needed.</p>
            <p style="text-align:center; color:#555; font-size:12px; margin-top:24px;">Powered by Gateo</p>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Event Cancelled Notification Error:", e)
        return False


def send_refund_request_notification(to_email, event_name, ticket_name, user_email):
    try:
        msg = Message(
            subject=f"Refund Request for {event_name}",
            recipients=[to_email]
        )

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto;">
            <h2 style="text-align:center; margin-bottom:8px;">Refund Requested</h2>
            <p style="text-align:center; font-size:15px; color:#374151; margin-bottom:20px;">
                A ticket holder has requested a refund for <strong>{event_name}</strong>.
            </p>
            <div style="background:#f9fafb; padding:15px; border-radius:8px; margin-bottom:20px;">
                <p style="margin:0 0 8px;"><strong>Ticket Name:</strong> {ticket_name}</p>
                <p style="margin:0;"><strong>Email:</strong> {user_email}</p>
            </div>
            <p style="color:#6b7280; font-size:14px;">The refund will be processed automatically after the 5-day window closes.</p>
            <p style="text-align:center; color:#555; font-size:12px; margin-top:24px;">Powered by Gateo</p>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Refund Request Notification Error:", e)
        return False


def send_purchase_notification_organiser_issued_ticket(
    organiser_email,
    event_name,
    ticket_type,
    ticket_name,
    ticket_quantity,
):
    try:
        msg = Message(
            subject=f"Organizer-issued ticket created for {event_name}",
            recipients=[organiser_email],
        )

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto;">
            <h2>{event_name}</h2>
            <p>Organizer-issued tickets have been created successfully.</p>
            <div style="background:#f9fafb; padding:15px; border-radius:8px;">
                <p><strong>Ticket Name:</strong> {ticket_name}</p>
                <p><strong>Ticket Type:</strong> {ticket_type}</p>
                <p><strong>Quantity:</strong> {ticket_quantity}</p>
            </div>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Organizer Notification Email Error:", e)
        return False




def send_purchase_notification_to_organiser(
    organiser_email,
    event_name,
    ticket_type,
    ticket_name,
    ticket_quantity,
    ticket_price=None,
):
    try:
        msg = Message(
            subject=f" New ticket has been created for {event_name}",
            recipients=[organiser_email],
        )

        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto;">
            <h2>{event_name}</h2>
            <p> New ticket have been created successfully.</p>
            <div style="background:#f9fafb; padding:15px; border-radius:8px;">
                <p><strong>Ticket Name:</strong> {ticket_name}</p>
                <p><strong>Ticket Type:</strong> {ticket_type}</p>
                <p><strong>Quantity:</strong> {ticket_quantity}</p>
                {f'<p><strong>Price:</strong> ${ticket_price:.2f}</p>' if ticket_price is not None else ''}
                <p><strong>Total Price:</strong> ${ticket_price * ticket_quantity:.2f if ticket_price is not None else 'N/A'}</p>
            </div>
        </div>
        """

        mail.send(msg)
        return True

    except Exception as e:
        print("Organizer Notification Email Error:", e)
        return False
