import qrcode
from uuid import uuid4
from io import BytesIO
import base64

def create_ticket(event_id, user_email, ticket_type, ticket_name):
    # 1. Generate unique ticket code
    ticket_code = str(uuid4())

    # 2. Embed bare ticket code to enforce internal app verification
    qr_data = ticket_code

    # 3. Build QR object
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4
    )

    qr.add_data(qr_data)
    qr.make(fit=True)

    # 4. Create QR image
    img = qr.make_image(fill_color="black", back_color="white")

    # 5. Convert to base64 (for email / frontend)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    # 6. Return ticket payload
    return {
        "ticket_code": ticket_code,
        "event_id": event_id,
        "user_email": user_email,
        "ticket_type": ticket_type,
        "ticket_name": ticket_name,
        "qr_base64": qr_base64
    }


if __name__ == "__main__":
    print(create_ticket(
        event_id=123,
        user_email="ajiboogbonna17@gmail.com",
        ticket_type="VIP",
        ticket_name="jibby",
        

    ))