from flask_mail import Message

from extensions import mail


def send_collaboration_request(to_email, event_name, role, team_member_login_link):
    try:
        msg = Message(
            subject=f"You have been invited to help manage {event_name}",
            recipients=[to_email],
        )
        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto;">
            <h2>Gateo team invitation</h2>
            <p>You have been added as <strong>{role}</strong> for <strong>{event_name}</strong>.</p>
            <p>Use the link below to sign in and access your team tools:</p>
            <p>
                <a href="{team_member_login_link}" style="display:inline-block;padding:10px 14px;background:#111827;color:#ffffff;text-decoration:none;border-radius:6px;">
                    Open team access
                </a>
            </p>
        </div>
        """
        mail.send(msg)
        return True
    except Exception as e:
        print("Team Invitation Email Error:", e)
        return False
