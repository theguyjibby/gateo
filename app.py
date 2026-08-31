from urllib import response
from uuid import uuid4
import secrets

from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import os
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
import datetime
from dotenv import load_dotenv
from sqlalchemy import ForeignKey
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from authlib.integrations.flask_client import OAuth
from ticketingqr import create_ticket as generate_qr_ticket  
from emailingticket import send_email, send_ticket_email_flask, send_purchase_notification_organiser_issued_ticket, send_purchase_notification_to_organiser
from extra import generate_unique_slug
import requests
import hmac
import hashlib


import re
import uuid
from mailingteam import send_collaboration_request
from cashier_mailing import send_withdrawal_link, send_withdrawal_success_email, send_cancellation_link





load_dotenv()



app = Flask(__name__, template_folder='templates')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///tickets.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('secret_key')
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY')
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')
PAYSTACK_PUBLIC_KEY_TEST = os.getenv('PAYSTACK_TEST_PUBLIC_KEY')
PAYSTACK_SECRET_KEY_TEST = os.getenv('PAYSTACK_TEST_SECRET_KEY')


BANK_CODES = {
    'access_bank': '044',
    'citibank_nigeria': '023',
    'ecobank_nigeria': '050',
    'fidelity_bank': '070',
    'first_bank_of_nigeria': '011',
    'first_city_monument_bank': '214',
    'guaranty_trust_bank': '058',
    'heritage_bank': '030',
    'keystone_bank': '082',
    'polaris_bank': '076',
    'stanbic_ibtc_bank': '221',
    'standard_chartered_bank': '068',
    'sterling_bank': '232',
    'united_bank_for_africa': '033',
    'union_bank_of_nigeria': '032',
    'unity_bank': '215',
    'wema_bank': '035',
    'zenith_bank': '057',
}


def resolve_account_paystack(account_number, bank_code):
    try:
        response = requests.get(
            'https://api.paystack.co/bank/resolve',
            params={
                'account_number': account_number,
                'bank_code': bank_code
            },
            headers={
                'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}'
            },
            timeout=30
        )
    except requests.RequestException:
        return None, 'Could not reach Paystack. Please try again later.'

    try:
        result = response.json()
    except ValueError:
        return None, 'Received an invalid response from Paystack.'

    if not response.ok or not result.get('status'):
        return None, result.get('message', 'Unable to verify bank account')

    return result.get('data'), None


db = SQLAlchemy(app)

oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.getenv('google_client_id'),
    client_secret=os.getenv('google_secret_key'),

    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',

    client_kwargs={
        'scope': 'openid email profile'
    }
)

from extensions import mail
from s3 import init_s3, upload_to_s3, delete_from_s3, get_media_url, is_s3_enabled

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

mail.init_app(app)

init_s3(app)
app.jinja_env.globals['get_media_url'] = get_media_url


class Organizers(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    bank_name = db.Column(db.String(100), nullable=True)
    account_number = db.Column(db.String(20), nullable=True)
    account_name = db.Column(db.String(200), nullable=True)

   


class Events(db.Model):
    event_id = db.Column(db.Integer, primary_key=True)
    event_name = db.Column(db.String(200), nullable=False)
    event_slug = db.Column(db.String(150), unique=True, nullable=False)
    event_date = db.Column(db.DateTime, nullable=False)
    event_end_date = db.Column(db.DateTime, nullable=False)
    event_time = db.Column(db.Time, nullable=True)
    event_country = db.Column(db.String(100), nullable=True)
    event_location = db.Column(db.String(200), nullable=False)
    event_description = db.Column(db.Text, nullable=True)
    organizers_id = db.Column(db.Integer, db.ForeignKey('organizers.id'), nullable=False)
    event_creation_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    event_media = db.relationship('Event_Media', backref='event', cascade='all, delete-orphan')
    TicketsOrganizers = db.relationship('TicketsOrganizers', backref='event', cascade='all, delete-orphan')
    TicketsUsers = db.relationship('TicketsUsers', backref='event', cascade='all, delete-orphan')
    website = db.Column(db.String(200), nullable=True)
    contact_number = db.Column(db.String(20), nullable=True)
    facebook_link = db.Column(db.String(200), nullable=True)
    twitter_link = db.Column(db.String(200), nullable=True)
    instagram_link = db.Column(db.String(200), nullable=True)
    tiktok_link = db.Column(db.String(200), nullable=True)
    public_email_contact = db.Column(db.String(200), nullable=True)
    is_public = db.Column(db.Boolean, default=True)
    is_suspended = db.Column(db.Boolean, default=False)
    is_cancelled = db.Column(db.Boolean, default=False)
    Team_Member = db.relationship('TeamMember', backref='event', cascade='all, delete-orphan')
    date_or_location_changed = db.Column(db.Boolean, default=False)
    date_location_changed_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_checkin_open(self):
        from datetime import date
        if self.event_date and date.today() < self.event_date.date():
            return False
        if self.event_end_date and datetime.datetime.now() >= self.event_end_date:
            return False
        return True

class TeamMember(db.Model):
    team_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    email = db.Column(db.String(150),nullable=False)
    role = db.Column(db.String(20), nullable=False, default='team_member')
    organzier_id = db.Column(db.Integer, db.ForeignKey('organizers.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


    

    @property
    def is_team_access(self):
        return True

class Event_Media(db.Model):
    media_id= db.Column(db.Integer, primary_key=True)
    filepath = db.Column(db.String(200), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)


    

class TicketsOrganizers(db.Model):
    ticket_type_id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    organizers_id = db.Column(db.Integer, db.ForeignKey('organizers.id'), nullable=False)
    ticket_type = db.Column(db.String(200), nullable=False)
    ticket_price = db.Column(db.Float, nullable=False)
    ticket_quantity = db.Column(db.Integer, nullable=True)
    ticket_description = db.Column(db.Text, nullable=True)
    ticket_selling_start_date = db.Column(db.DateTime, nullable=True)
    ticket_selling_end_date = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    TicketsUsers = db.relationship('TicketsUsers', backref='ticket_type_ref', lazy=True)


class TicketsUsers(db.Model):

    ticket_id = db.Column(db.Integer, primary_key=True)
    ticket_unique_id = db.Column(db.String(100), unique=True, nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    user_email = db.Column(db.String(150), nullable=False)
    ticket_type = db.Column(db.String(200), nullable=False)
    ticket_type_id = db.Column(db.Integer,db.ForeignKey('tickets_organizers.ticket_type_id'), nullable=False)
    ticket_price = db.Column(db.Float, nullable=False, default=0.0)
    ticket_quantity= db.Column(db.Integer, nullable=False, default=1)
    ticket_name = db.Column(db.String(200), nullable=False)
    purchase_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    organizers_id = db.Column(db.Integer, db.ForeignKey('organizers.id'), nullable=False)
    is_successful = db.Column(db.Boolean, default=False)
    is_free = db.Column(db.Boolean, default=False)
    is_used = db.Column(db.Boolean, default=False)
    is_admin_issued = db.Column(db.Boolean, default=False)
    payment_reference = db.Column(db.String(100), nullable=True)
    refund_requested = db.Column(db.Boolean, default=False)
    refund_requested_at = db.Column(db.DateTime, nullable=True)


class Withdrawals(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(100), unique=True, nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizers.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    amount = db.Column(db.Float, nullable=True)
    bank_name = db.Column(db.String(200), nullable=True)
    account_number = db.Column(db.String(20), nullable=True)
    account_name = db.Column(db.String(200), nullable=True)
    paystack_recepient_code = db.Column(db.String(100), nullable=True)
    paystack_transfer_ref = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class Cancellations(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(100), unique=True, nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizers.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.event_id'), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    is_used = db.Column(db.Boolean, default=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


def set_team_member_session(member, event_id):
    session.permanent = True
    session['team_member'] = {
        'team_id': member.team_id,
        'member_email': member.email,
        'role': member.role,
        'organzier_id': member.organzier_id,
        'event_id': event_id
    }


def get_active_team_member(event_id, allowed_roles=None):
    team_session = session.get('team_member')
    if not team_session or team_session.get('event_id') != event_id:
        return None

    member = TeamMember.query.filter_by(
        team_id=team_session.get('team_id'),
        event_id=event_id,
        email=team_session.get('member_email')
    ).first()

    if not member:
        session.pop('team_member', None)
        return None

    # Keep the cookie aligned with the database in case the role changed.
    if team_session.get('role') != member.role:
        set_team_member_session(member, event_id)

    if allowed_roles and member.role not in allowed_roles:
        return None

    return member


def redirect_team_member_by_role(role, event_id):
    if role == 'admin':
        return redirect(url_for('get_paid_tickets', event_id=event_id))
    if role == 'team_member':
        return redirect(url_for('scanner_page', event_id=event_id))
    return jsonify({'message': 'Unauthorized'}), 403


def parse_time_string(value):
    """Parse an HH:MM or HH:MM:SS string into a datetime.time, or None if invalid/empty."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def event_full_withdrawal_datetime(event):
    """Moment full withdrawal unlocks: 11:59 PM on the end date, regardless of the organizer's custom end time."""
    if not event.event_end_date:
        return None
    return datetime.datetime.combine(event.event_end_date.date(), datetime.time(23, 59, 59))


login_manager = LoginManager(app)
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Organizers, int(user_id))


@app.route('/')
def landing():
    now = datetime.datetime.now()
    events = Events.query.filter(
        db.or_(Events.event_end_date >= now, db.and_(Events.event_end_date.is_(None), Events.event_date >= now))
    ).order_by(Events.event_date.asc()).all()
    live_events_data = []
    for event in events:
        if event.is_public and not getattr(event, 'is_suspended', False) and not getattr(event, 'is_cancelled', False):
            media = Event_Media.query.filter_by(event_id=event.event_id).first()
            event_media = media.filepath if media else None
            tickets = TicketsOrganizers.query.filter_by(event_id=event.event_id, is_active=True).all()
            lowest_price = min((t.ticket_price for t in tickets), default=0)
            live_events_data.append({
                'event_id': event.event_id,
                'event_name': event.event_name,
                'event_date': event.event_date.strftime('%d %b %Y') if event.event_date else None,
                'event_time': event.event_time.strftime('%I:%M %p') if event.event_time else None,
                'event_country': event.event_country,
                'event_location': event.event_location,
                'event_description': event.event_description,
                'organizer_name': db.session.get(Organizers, event.organizers_id).username if event.organizers_id else None,
                'event_slug': event.event_slug,
                'media': event_media,
                'lowest_price': lowest_price,
                'ticket_count': len(tickets)
            })
    return render_template('landing.html', events=live_events_data)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('signup.html')
    data = request.get_json() or {}
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    verify_password = data.get('verify_password')
    if not username or not email or not password or not verify_password:
        return jsonify({'message': 'Missing required fields'}), 400

    if password != verify_password:
        return jsonify({'message': 'Passwords do not match'}), 400
    
    if len(password) < 8:
        return jsonify({'message': 'Password must be at least 8 characters long'}), 400
    
    if not username.isascii():
        return jsonify({'message': 'Username must use only English letters, numbers, and symbols'}), 400

    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return jsonify({'message': 'Invalid email address'}), 400

    if Organizers.query.filter_by(email=email).first():
        return jsonify({'message': 'Email already registered'}), 400
    if Organizers.query.filter(Organizers.username.ilike(username)).first():
        return jsonify({'message': 'Username not available'}), 400
    

    
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    
    new_user = Organizers   (username=username, email=email, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': 'organizer registered successfully'}), 201


@app.route('/verify_email', methods= ['GET','POST'])
def verify_email():
    if request.method == 'GET':
        return render_template('verify_email.html')
    data = request.get_json()
    code = data.get('code')
    if not code:
        return jsonify({'message': 'Verification code is required'}), 400

    
@app.route('/resend_verification_code', methods=['POST'])
def resend_verification_code():
    data = request.get_json()
    email = data.get('email')
    if not email:
        return jsonify({'message': 'Email is required'}), 400
    

    

    
    

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    data =request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'message': 'fill in all fields'})
    organizer = Organizers.query.filter_by(email=email).first()
    if not organizer or not check_password_hash(organizer.password, password):
        return jsonify({'message': 'Invalid email or password'}), 401
        
    login_user(organizer)

    return jsonify({'message': 'Logged in successfully'}), 200








@app.route('/login/google')
def login_google():
    redirect_uri = url_for('authorize_google', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/google/callback')
def authorize_google():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    email = user_info['email']


    organizer = Organizers.query.filter_by(email=email).first()
    if not organizer:   
        return redirect(url_for('register')), 400


    
    login_user(organizer)
    return redirect(url_for('dashboard'))



@app.route('/dashboard')
@login_required
def dashboard():
    username = current_user.username
    return render_template('dashboard.html', username=username)

@app.route('/events', methods=['GET'])
def live_events():
    now = datetime.datetime.now()
    events = Events.query.filter(
        db.or_(Events.event_end_date >= now, db.and_(Events.event_end_date.is_(None), Events.event_date >= now))
    ).order_by(Events.event_date.asc()).all()
    live_events_data = []
    for event in events:
        if event.is_public and not getattr(event, 'is_suspended', False) and not getattr(event, 'is_cancelled', False):
            media = Event_Media.query.filter_by(event_id=event.event_id).first()
            event_media = media.filepath if media else None
            tickets = TicketsOrganizers.query.filter_by(event_id=event.event_id, is_active=True).all()
            lowest_price = min((t.ticket_price for t in tickets), default=0)
            live_events_data.append({
                'event_id': event.event_id,
                'event_name': event.event_name,
                'event_date': event.event_date.strftime('%d %b %Y') if event.event_date else None,
                'event_time': event.event_time.strftime('%I:%M %p') if event.event_time else None,
                'event_country': event.event_country,
                'event_location': event.event_location,
                'event_description': event.event_description,
                'organizer_name': db.session.get(Organizers, event.organizers_id).username if event.organizers_id else None,
                'event_slug': event.event_slug,
                'media': event_media,
                'lowest_price': lowest_price,
                'ticket_count': len(tickets)
            })
    return render_template('live_events.html', events=live_events_data)
            



@app.route('/create_event', methods=['GET', 'POST'])
@login_required
def create_event():
    if request.method == 'POST':
        event_name = request.form.get('event_name')
        event_date = request.form.get('event_date')
        event_time = request.form.get('event_time')
        event_country = request.form.get('event_country')
        event_location = request.form.get('event_location')
        event_description = request.form.get('event_description')
        event_custom_slug = request.form.get('event_slug')
        website = request.form.get('website')
        contact_number = request.form.get('contact_number')
        facebook_link = request.form.get('facebook_link')
        twitter_link = request.form.get('twitter_link')
        instagram_link = request.form.get('instagram_link')
        tiktok_link = request.form.get('tiktok_link')
        public_email_contact = request.form.get('public_email_contact')
        event_end_date = request.form.get('event_end_date')
        event_end_time = request.form.get('event_end_time')
        is_public = request.form.get('is_public') == 'true'

        
        uploaded_files = request.files.getlist('event_media')

        if not event_name or not event_date or not event_time or not event_country or not event_location:
            return jsonify({'message': 'Missing required fields'}), 400

        if not event_name.isascii():
            return jsonify({'message': 'Event name must use only English letters, numbers, and symbols'}), 400

        if Events.query.filter(Events.event_name.ilike(event_name)).first():
            return jsonify({'message': 'Event name not available'}), 400

        if event_custom_slug:
            if not re.match(r'^[a-z0-9-_]+$', event_custom_slug.lower()):
                return jsonify({'message': 'Invalid custom url slug (use only letters, numbers, and dashes)'}), 400    
            slug = generate_unique_slug(event_custom_slug, Events)
        else:
            slug = generate_unique_slug(event_name, Events)

        try:
            event_date_obj = datetime.datetime.strptime(event_date, '%Y-%m-%d')
            event_time_obj = datetime.datetime.strptime(event_time, '%H:%M:%S').time()
            end_date_obj = datetime.datetime.strptime(event_end_date, '%Y-%m-%d') if event_end_date else None
            end_time_obj = parse_time_string(event_end_time)
            event_end_date_obj = None
            if end_date_obj:
                event_end_date_obj = datetime.datetime.combine(end_date_obj.date(), end_time_obj or datetime.time(23, 59, 59))

            from datetime import date
            if event_date_obj.date() < date.today():
                return jsonify({'message': 'Event date cannot be assigned to a past date.'}), 400

            if event_end_date_obj and event_end_date_obj < datetime.datetime.combine(event_date_obj.date(), event_time_obj):
                return jsonify({'message': 'Event end must be after the event start.'}), 400

        except ValueError:
            return jsonify({'message': 'Invalid date or time format. Please use YYYY-MM-DD and HH:MM:SS.'}), 400

        new_event = Events(
            event_name=event_name,
            event_date=event_date_obj,
            event_end_date=event_end_date_obj,
            event_time=event_time_obj,
            event_slug=slug,
            event_country=event_country,
            event_location=event_location,
            event_description=event_description,
            organizers_id=current_user.id,
            website=website,
            contact_number=contact_number,
            facebook_link=facebook_link,
            twitter_link=twitter_link,
            instagram_link=instagram_link,
            tiktok_link=tiktok_link,
            public_email_contact=public_email_contact,
            is_public=is_public
        )
        db.session.add(new_event)
        db.session.commit()

        if uploaded_files:
            for file in uploaded_files:
                if file and file.filename != '':
                    if is_s3_enabled():
                        key = upload_to_s3(file, folder='uploads')
                        filepath = key
                    else:
                        upload_folder = os.path.join(app.root_path, 'static', 'upload')
                        os.makedirs(upload_folder, exist_ok=True)
                        filename = secure_filename(file.filename)
                        unique_filename = str(uuid4())[:8] + "_" + filename
                        filepath_local = os.path.join(upload_folder, unique_filename)
                        file.save(filepath_local)
                        filepath = f"static/upload/{unique_filename}"

                    new_media = Event_Media(
                        event_id=new_event.event_id,
                        filepath=filepath
                    )
                    db.session.add(new_media)
            db.session.commit()
        return jsonify({'message': 'Event created successfully','event_id': new_event.event_id}), 201
    return render_template('create_event.html')

@app.route('/create_event/edit/<int:event_id>', methods=['GET','POST'])
@login_required
def edit_event(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403
        
    if request.method == 'POST':
        if getattr(event, 'is_suspended', False):
            return jsonify({'message': 'Event is currently suspended.'}), 403
        
    event_media = Event_Media.query.filter_by(event_id=event_id).all()
    
    
    if request.method == 'POST':

        data = request.form
        event.event_name = data.get('event_name', event.event_name)

        if not event.event_name.isascii():
            return jsonify({'message': 'Event name must use only English letters, numbers, and symbols'}), 400
        
        if data.get('event_date'):
            new_date = datetime.datetime.strptime(data.get('event_date'), '%Y-%m-%d')
            from datetime import date
            if new_date.date() < date.today():
                return jsonify({'message': 'Event date cannot be updated to a past date.'}), 400
            
        has_sold_tickets = TicketsUsers.query.filter_by(event_id=event_id, is_successful=True).first() is not None

        if has_sold_tickets:
            event.event_description = data.get('event_description', event.event_description)
            event.event_slug = data.get('event_slug', event.event_slug)
            event.event_name = data.get('event_name', event.event_name)
            event.website = data.get('website', event.website)
            event.contact_number = data.get('contact_number', event.contact_number)
            event.facebook_link = data.get('facebook_link', event.facebook_link)
            event.twitter_link = data.get('twitter_link', event.twitter_link)
            event.instagram_link = data.get('instagram_link', event.instagram_link)
            event.tiktok_link = data.get('tiktok_link', event.tiktok_link)
            event.public_email_contact= data.get('public_email_contact', event.public_email_contact)
            event.is_public = data.get('is_public') == 'true'
        else:
            event.event_date = new_date
            event.event_name = data.get('event_name', event.event_name)
            event.event_time = datetime.datetime.strptime(data.get('event_time'), '%H:%M:%S').time() if data.get('event_time') else event.event_time
            event.event_country = data.get('event_country', event.event_country)
            event.event_location = data.get('event_location', event.event_location)
            event.event_description = data.get('event_description', event.event_description)
            event.event_slug = data.get('event_slug', event.event_slug)
            event.website = data.get('website', event.website)
            event.contact_number = data.get('contact_number', event.contact_number)
            event.facebook_link = data.get('facebook_link', event.facebook_link)
            event.twitter_link = data.get('twitter_link', event.twitter_link)
            event.instagram_link = data.get('instagram_link', event.instagram_link)
            event.tiktok_link = data.get('tiktok_link', event.tiktok_link)
            event.public_email_contact= data.get('public_email_contact', event.public_email_contact)
            if data.get('event_end_date'):
                end_date_obj = datetime.datetime.strptime(data.get('event_end_date'), '%Y-%m-%d')
                end_time_obj = parse_time_string(data.get('event_end_time'))
                event.event_end_date = datetime.datetime.combine(end_date_obj.date(), end_time_obj or datetime.time(23, 59, 59))
            event.is_public = data.get('is_public') == 'true'

            if event.event_end_date and event.event_time and event.event_date:
                if event.event_end_date < datetime.datetime.combine(event.event_date.date(), event.event_time):
                    return jsonify({'message': 'Event end must be after the event start.'}), 400

        # Remove media that user chose to delete
        removed_media_ids = request.form.getlist('remove_media[]')
        if removed_media_ids:
            for m_id in removed_media_ids:
                media_to_delete = db.session.get(Event_Media, int(m_id))
                if media_to_delete and media_to_delete.event_id == event_id:
                    if is_s3_enabled():
                        delete_from_s3(media_to_delete.filepath)
                    else:
                        local_path = os.path.join(app.root_path, media_to_delete.filepath)
                        if os.path.exists(local_path):
                            os.remove(local_path)
                    db.session.delete(media_to_delete)

        uploaded_files = request.files.getlist('event_media')
        if uploaded_files and uploaded_files[0].filename != '':
            for file in uploaded_files:
                if file and file.filename != '':
                    if is_s3_enabled():
                        key = upload_to_s3(file, folder='uploads')
                        filepath = key
                    else:
                        upload_folder = os.path.join(app.root_path, 'static', 'upload')
                        os.makedirs(upload_folder, exist_ok=True)
                        filename = secure_filename(file.filename)
                        unique_filename = str(uuid4())[:8] + "_" + filename
                        filepath_local = os.path.join(upload_folder, unique_filename)
                        file.save(filepath_local)
                        filepath = f"static/upload/{unique_filename}"

                    media = Event_Media(event_id=event_id, filepath=filepath)
                    db.session.add(media)

        db.session.commit()
        return jsonify({'message': 'Event updated successfully', 'event_slug': event.event_slug}), 200
    
    
    
    has_sold_tickets = TicketsUsers.query.filter_by(event_id=event_id, is_successful=True).first() is not None
    return render_template('edit_event.html', event=event, event_media=event_media, has_sold_tickets=has_sold_tickets)


@app.route('/create_event/edit/date_location/<int:event_id>', methods=['GET','POST'])
def change_location_date(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403

    if getattr(event, 'is_suspended', False):
        return jsonify({'message': 'Event is currently suspended.'}), 403

    has_sold_tickets = TicketsUsers.query.filter_by(event_id=event_id, is_successful=True).first() is not None
    if not has_sold_tickets:
        return jsonify({'message': 'No tickets sold yet. Use the regular edit form.'}), 400

    has_withdrawn = Withdrawals.query.filter_by(event_id=event_id, organizer_id=current_user.id, is_used=True).first() is not None
    if has_withdrawn:
        return jsonify({'message': 'You have already made a withdrawal for this event. Date and location cannot be changed.'}), 403

    if request.method == 'POST':
        data = request.get_json()
        new_date = data.get('event_date')
        new_location = data.get('event_location')
        new_end_date = data.get('event_end_date')
        new_end_time = data.get('event_end_time')

        if not new_date and not new_location and not new_end_date and not new_end_time:
            return jsonify({'message': 'No changes provided'}), 400

        old_date = event.event_date.strftime('%B %d, %Y') if event.event_date else None
        old_end_date = event.event_end_date.strftime('%B %d, %Y') if event.event_end_date else None
        old_location = event.event_location

        if new_date:
            try:
                new_date_obj = datetime.datetime.strptime(new_date, '%Y-%m-%d')
                from datetime import date
                if new_date_obj.date() < date.today():
                    return jsonify({'message': 'Event date cannot be updated to a past date.'}), 400

                if new_date_obj.date() < event.event_date.date():
                    return jsonify({'message': 'Event date cannot be earlier than the previous event date.'}), 400

                event.event_date = new_date_obj

            except ValueError:
                return jsonify({'message': 'Invalid date format. Please use YYYY-MM-DD.'}), 400

        if new_location:
            event.event_location = new_location

        if new_end_date:
            try:
                end_date_obj = datetime.datetime.strptime(new_end_date, '%Y-%m-%d')
                end_time_obj = parse_time_string(new_end_time)
                new_end_datetime = datetime.datetime.combine(end_date_obj.date(), end_time_obj or datetime.time(23, 59, 59))
                start_datetime = datetime.datetime.combine(event.event_date.date(), event.event_time) if event.event_time else event.event_date
                if new_end_datetime < start_datetime:
                    return jsonify({'message': 'End date/time cannot be earlier than the start date/time.'}), 400
                if event.event_end_date and new_end_datetime.date() < event.event_end_date.date():
                    return jsonify({'message': 'End date cannot be earlier than the previous end date.'}), 400
                event.event_end_date = new_end_datetime
            except ValueError:
                return jsonify({'message': 'Invalid end date format. Please use YYYY-MM-DD.'}), 400

        event.date_or_location_changed = True
        event.date_location_changed_at = datetime.datetime.utcnow()

        db.session.commit()

        ticket_holders = TicketsUsers.query.filter_by(event_id=event_id, is_successful=True).distinct(TicketsUsers.user_email).all()
        from emailingticket import send_date_location_change_notification
        new_date_display = event.event_date.strftime('%B %d, %Y') if event.event_date else None
        new_end_date_display = event.event_end_date.strftime('%B %d, %Y') if event.event_end_date else None
        new_location_display = event.event_location
        refund_deadline = (datetime.datetime.utcnow() + datetime.timedelta(days=5)).strftime('%B %d, %Y')

        for holder in ticket_holders:
            send_date_location_change_notification(
                to_email=holder.user_email,
                event_name=event.event_name,
                old_date=f"{old_date} - {old_end_date}" if old_end_date else old_date,
                new_date=f"{new_date_display} - {new_end_date_display}" if new_end_date_display else new_date_display,
                old_location=old_location,
                new_location=new_location_display,
                refund_deadline=refund_deadline,
                event_slug=event.event_slug
            )

        return jsonify({'message': 'Event date and/or location updated successfully. Ticket holders have been notified.'}), 200

    ticket_count = TicketsUsers.query.filter_by(event_id=event_id, is_successful=True).count()
    refund_window_active = False
    if getattr(event, 'date_location_changed_at', None):
        window_end = event.date_location_changed_at + datetime.timedelta(days=5)
        refund_window_active = datetime.datetime.utcnow() < window_end
    return render_template('change_location_date.html', event=event, ticket_count=ticket_count, refund_window_active=refund_window_active)


@app.route('/event/<string:event_slug>/request-refund', methods=['GET', 'POST'])
def request_refund(event_slug):
    event = Events.query.filter_by(event_slug=event_slug).first()
    if not event:
        return jsonify({'message': 'Event not found'}), 404

    if not getattr(event, 'date_location_changed_at', None):
        return jsonify({'message': 'No date/location change has been made for this event.'}), 400

    window_end = event.date_location_changed_at + datetime.timedelta(days=5)
    if datetime.datetime.utcnow() > window_end:
        return jsonify({'message': 'The 5-day refund window has closed.'}), 400

    if request.method == 'GET':
        return render_template('request_refund.html', event=event, window_end=window_end)

    data = request.get_json()
    user_email = data.get('email')
    ticket_unique_id = data.get('ticket_unique_id')

    if not user_email or not ticket_unique_id:
        return jsonify({'message': 'Email and ticket ID are required.'}), 400

    ticket = TicketsUsers.query.filter_by(
        event_id=event.event_id,
        user_email=user_email,
        ticket_unique_id=ticket_unique_id,
        is_successful=True
    ).first()
    if not ticket:
        return jsonify({'message': 'Ticket not found.'}), 404

    if ticket.is_used:
        return jsonify({'message': 'This ticket has already been used and is not eligible for a refund.'}), 400

    if ticket.purchase_date >= event.date_location_changed_at:
        return jsonify({'message': 'This ticket was purchased after the date/location change and is not eligible for a refund.'}), 400

    if ticket.refund_requested:
        return jsonify({'message': 'A refund has already been requested for this ticket.'}), 400

    ticket.refund_requested = True
    ticket.refund_requested_at = datetime.datetime.utcnow()
    db.session.commit()

    from emailingticket import send_refund_request_notification
    organizer = db.session.get(Organizers, event.organizers_id)
    send_refund_request_notification(
        to_email=organizer.email,
        event_name=event.event_name,
        ticket_name=ticket.ticket_name,
        user_email=ticket.user_email
    )

    return jsonify({'message': 'Refund request submitted successfully. You will receive a confirmation email.'}), 200


@app.route('/create_event/suspend/<int:event_id>', methods=['POST'])
@login_required
def suspend_event(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403
    if event.is_cancelled:
        return jsonify({'message': 'This event has been cancelled and cannot be suspended.'}), 400

    event.is_suspended = not getattr(event, 'is_suspended', False)
    db.session.commit()
    status = 'suspended' if event.is_suspended else 'resumed'
    return jsonify({'message': f'Event successfully {status}.'}), 200


@app.route('/create_event/cancel/<int:event_id>', methods=['POST'])
@login_required
def request_event_cancellation(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403

    if event.is_cancelled:
        return jsonify({'message': 'This event has already been cancelled.'}), 400

    from cashier_mailing import send_cancellation_link

    existing = Cancellations.query.filter_by(
        event_id=event_id,
        organizer_id=current_user.id,
        is_used=False
    ).order_by(Cancellations.created_at.desc()).first()

    if existing:
        token_age = datetime.datetime.utcnow() - existing.created_at
        if token_age < datetime.timedelta(minutes=5):
            organizer_email = db.session.get(Organizers, event.organizers_id).email
            send_cancellation_link(
                organizer_email=organizer_email,
                event_name=event.event_name,
                cancel_token=existing.token,
                base_url=request.host_url
            )
            return jsonify({'message': 'Cancellation request sent. Check your email to confirm.'}), 200

    token = secrets.token_urlsafe(32)
    cancellation = Cancellations(
        token=token,
        organizer_id=current_user.id,
        event_id=event_id
    )
    db.session.add(cancellation)
    db.session.commit()

    organizer_email = db.session.get(Organizers, event.organizers_id).email
    sent = send_cancellation_link(
        organizer_email=organizer_email,
        event_name=event.event_name,
        cancel_token=token,
        base_url=request.host_url
    )
    if not sent:
        return jsonify({'message': 'Failed to send cancellation link'}), 500
    return jsonify({'message': 'Cancellation request sent. Check your email to confirm.'}), 200


@app.route('/create_event/delete/<int:event_id>', methods=['DELETE'])
@login_required
def delete_event(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403

    if event.is_cancelled:
        return jsonify({'message': 'This event has already been cancelled.'}), 400

    withdrawal_exists = db.session.query(Withdrawals).filter_by(event_id=event.event_id).first() is not None
    if withdrawal_exists:
        return jsonify({'message': 'Cancellation blocked. A withdrawal has already been made for this event.'}), 400

    paid_purchased = db.session.query(TicketsUsers).filter_by(
        event_id=event.event_id,
        is_successful=True,
        is_free=False,
        is_admin_issued=False
    ).filter(TicketsUsers.ticket_price > 0).all()

    if paid_purchased:
        refund_total = 0
        for ticket in paid_purchased:
            if not ticket.refund_requested:
                ticket.refund_requested = True
                ticket.refund_requested_at = datetime.datetime.utcnow()
            refund_total += ticket.ticket_price * 0.94

        event.is_cancelled = True
        db.session.commit()

        from emailingticket import send_event_cancelled_notification
        paid_emails = db.session.query(TicketsUsers.user_email).filter_by(
            event_id=event.event_id,
            is_successful=True,
            is_free=False,
            is_admin_issued=False
        ).filter(TicketsUsers.ticket_price > 0).distinct()
        for email in paid_emails:
            send_event_cancelled_notification(
                to_email=email[0],
                event_name=event.event_name
            )

        return jsonify({'message': f'Event cancelled. Refunds of ₦{refund_total:,.2f} have been initiated for all buyers.'}), 200

    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted successfully'}), 200


@app.route('/cashier/cancel', methods=['GET'])
def cancel_event_dashboard():
    token = request.args.get('token')
    if not token:
        return render_template('expired_link.html', message='Invalid cancellation link'), 400

    cancellation = Cancellations.query.filter_by(token=token).first()
    if not cancellation:
        return render_template('expired_link.html', message='Invalid cancellation link'), 400

    if cancellation.is_used:
        return render_template('expired_link.html', message='This cancellation link has already been used'), 400

    token_age = datetime.datetime.utcnow() - cancellation.created_at
    if token_age > datetime.timedelta(minutes=5):
        return render_template('expired_link.html', message='This cancellation link has expired'), 400

    event = db.session.get(Events, cancellation.event_id)
    if not event:
        return render_template('expired_link.html', message='Event not found'), 404

    paid_tickets = db.session.query(TicketsUsers).filter_by(
        event_id=event.event_id,
        is_successful=True,
        is_free=False,
        is_admin_issued=False
    ).filter(TicketsUsers.ticket_price > 0).all()
    free_purchased = db.session.query(TicketsUsers).filter_by(
        event_id=event.event_id,
        is_successful=True,
        is_free=True
    ).count()
    total_sold = db.session.query(TicketsUsers).filter_by(
        event_id=event.event_id,
        is_successful=True
    ).count()
    withdrawal = db.session.query(Withdrawals).filter_by(event_id=event.event_id).first()

    has_paid_tickets = len(paid_tickets) > 0
    has_withdrawal = withdrawal is not None

    ticket_count = 0
    refund_total = 0
    for ticket in paid_tickets:
        ticket_count += ticket.ticket_quantity or 1
        refund_total += ticket.ticket_price * (ticket.ticket_quantity or 1) * 0.94

    return render_template('cancel_event.html',
                           event=event,
                           token=token,
                           has_paid_tickets=has_paid_tickets,
                           has_withdrawal=has_withdrawal,
                           paid_ticket_count=ticket_count,
                           free_ticket_count=free_purchased,
                           total_sold=total_sold,
                           refund_total=refund_total)


@app.route('/cashier/cancel', methods=['POST'])
def cancel_event_confirmed():
    data = request.get_json() or {}
    token = data.get('token') or request.args.get('token')
    reason = (data.get('reason') or '').strip()
    if not token:
        return jsonify({'message': 'Invalid cancellation link'}), 400

    cancellation = Cancellations.query.filter_by(token=token).first()
    if not cancellation:
        return jsonify({'message': 'Invalid cancellation link'}), 400

    if cancellation.is_used:
        return jsonify({'message': 'This cancellation link has already been used'}), 400

    token_age = datetime.datetime.utcnow() - cancellation.created_at
    if token_age > datetime.timedelta(minutes=5):
        return jsonify({'message': 'This cancellation link has expired'}), 400

    event = db.session.get(Events, cancellation.event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404

    if event.is_cancelled:
        return jsonify({'message': 'This event has already been cancelled.'}), 400

    withdrawal_exists = db.session.query(Withdrawals).filter_by(event_id=event.event_id).first() is not None
    if withdrawal_exists:
        return jsonify({'message': 'Cancellation blocked. A withdrawal has already been made for this event.'}), 400

    cancellation.reason = reason
    cancellation.is_used = True
    cancellation.used_at = datetime.datetime.utcnow()

    paid_purchased = db.session.query(TicketsUsers).filter_by(
        event_id=event.event_id,
        is_successful=True,
        is_free=False,
        is_admin_issued=False
    ).filter(TicketsUsers.ticket_price > 0).all()

    if paid_purchased:
        refund_total = 0
        for ticket in paid_purchased:
            if not ticket.refund_requested:
                ticket.refund_requested = True
                ticket.refund_requested_at = datetime.datetime.utcnow()
            refund_total += ticket.ticket_price * 0.94

        event.is_cancelled = True
        db.session.commit()

        from emailingticket import send_event_cancelled_notification
        paid_emails = db.session.query(TicketsUsers.user_email).filter_by(
            event_id=event.event_id,
            is_successful=True,
            is_free=False,
            is_admin_issued=False
        ).filter(TicketsUsers.ticket_price > 0).distinct()
        for email in paid_emails:
            send_event_cancelled_notification(
                to_email=email[0],
                event_name=event.event_name
            )

        return jsonify({'message': f'Event cancelled. Refunds of ₦{refund_total:,.2f} have been initiated for all buyers.'}), 200

    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted successfully'}), 200


@app.route('/event/organizer', methods=['GET'])
@login_required
def get_organizer_events():
    organizer_id = current_user.id
    # Using order_by to get newest first
    events = db.session.query(Events).filter_by(organizers_id=organizer_id, is_cancelled=False).order_by(Events.event_creation_date.desc()).all()
    
    events_data = []
    for event in events:
        media = db.session.query(Event_Media).filter_by(event_id=event.event_id).first()
        sold_count = db.session.query(TicketsUsers).filter_by(event_id=event.event_id, is_successful=True).count()
        has_withdrawal = db.session.query(Withdrawals).filter_by(event_id=event.event_id).first() is not None
        events_data.append({
            'event_id': event.event_id,
            'event_name': event.event_name,
            'event_date': event.event_date.strftime('%Y-%m-%d') if event.event_date else None,
            'event_time': event.event_time.strftime('%H:%M:%S') if event.event_time else None,
            'event_country': event.event_country,
            'event_location': event.event_location,
            'event_description': event.event_description,
            'organizers_id': event.organizers_id,
            'event_creation_date': event.event_creation_date.isoformat() if event.event_creation_date else None,
            'event_slug': event.event_slug,
            'media': get_media_url(media.filepath) if media else None,
            'is_suspended': getattr(event, 'is_suspended', False),
            'is_public': getattr(event, 'is_public', True),
            'is_cancelled': getattr(event, 'is_cancelled', False),
            'has_sold_tickets': sold_count > 0,
            'has_withdrawal': has_withdrawal
        })
    return jsonify({'events': events_data}), 200








@app.route('/tickets/organizer/<int:event_id>', methods=['GET', 'POST'])
@login_required
def create_ticket(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403

    if request.method == 'POST':
        if getattr(event, 'is_suspended', False):
            return jsonify({'message': 'Event is currently suspended.'}), 403
            
        data_list = request.get_json()
        if not isinstance(data_list, list):
            data_list = [data_list]
        
        valid_tickets_added = False
        for data in data_list:
            t_id = data.get('ticket_type_id')
            ticket_type = data.get('ticket_type')
            ticket_price = data.get('ticket_price')
            
            if not ticket_type:
                continue

            ticket_price = 0 if ticket_price is None or str(ticket_price).strip() == "" else ticket_price
                
            ticket_quantity = data.get('ticket_quantity')
            ticket_description = data.get('ticket_description')
            t_start = data.get('ticket_selling_start_date')
            t_end = data.get('ticket_selling_end_date')

            if t_id:
                # Update existing ticket
                existing_ticket = db.session.get(TicketsOrganizers, int(t_id))
                if existing_ticket and existing_ticket.event_id == event_id:
                    existing_ticket.ticket_type = ticket_type
                    existing_ticket.ticket_price = float(ticket_price)
                    existing_ticket.ticket_quantity = int(ticket_quantity) if ticket_quantity and str(ticket_quantity).strip() != "" else None
                    existing_ticket.ticket_description = ticket_description
                    existing_ticket.ticket_selling_start_date = datetime.datetime.strptime(t_start, '%Y-%m-%d') if t_start else existing_ticket.ticket_selling_start_date
                    existing_ticket.ticket_selling_end_date = datetime.datetime.strptime(t_end, '%Y-%m-%d') if t_end else existing_ticket.ticket_selling_end_date
                    existing_ticket.is_active = data.get('is_active', True)
                    valid_tickets_added = True
            else:
                # Default assignments for new tickets only if not provided
                if not t_start:
                    t_start = event.event_creation_date.strftime('%Y-%m-%d')
                if not t_end:
                    t_end = event.event_end_date.strftime('%Y-%m-%d') if event.event_end_date else (event.event_date.strftime('%Y-%m-%d') if event.event_date else t_start)

                new_ticket = TicketsOrganizers(
                    event_id=event_id,
                    organizers_id=current_user.id,
                    ticket_type=ticket_type,
                    ticket_price=float(ticket_price),
                    ticket_quantity=int(ticket_quantity) if ticket_quantity and str(ticket_quantity).strip() != "" else None,
                    ticket_description=ticket_description,
                    ticket_selling_start_date=datetime.datetime.strptime(t_start, '%Y-%m-%d') if t_start else None,
                    ticket_selling_end_date=datetime.datetime.strptime(t_end, '%Y-%m-%d') if t_end else None,
                    is_active=data.get('is_active', True)
                )
                db.session.add(new_ticket)
                valid_tickets_added = True
            
        if not valid_tickets_added:
            return jsonify({'message': 'No valid tickets provided'}), 400

        db.session.commit()
        return jsonify({'message': 'Tickets created successfully'}), 201

    tickets = TicketsOrganizers.query.filter_by(event_id=event_id).all()
    # Pre-calculate sold counts
    for t in tickets:
        t.sold_count = TicketsUsers.query.filter_by(event_id=event_id, ticket_type_id=t.ticket_type_id, is_successful=True).count()
        t.is_sold_out = (t.sold_count >= t.ticket_quantity) if t.ticket_quantity is not None else False

    return render_template('create_ticket.html', event=event, tickets=tickets)


@app.route('/tickets/organizer/edit/<int:ticket_type_id>', methods=['POST'])
@login_required
def edit_ticket(ticket_type_id):
    ticket_type = db.session.get(TicketsOrganizers, ticket_type_id)
    if not ticket_type:
        return jsonify({'message': 'Ticket not found'}), 404
    if ticket_type.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403
        
    event = ticket_type.event
    if getattr(event, 'is_suspended', False):
        return jsonify({'message': 'Event is currently suspended.'}), 403

    data = request.get_json() or {}
    ticket_type.ticket_type = data.get('ticket_type', ticket_type.ticket_type)
    if 'ticket_price' in data:
        ticket_price = data.get('ticket_price')
        ticket_type.ticket_price = 0 if ticket_price is None or str(ticket_price).strip() == "" else float(ticket_price)
    if 'ticket_quantity' in data:
        ticket_quantity = data.get('ticket_quantity')
        ticket_type.ticket_quantity = int(ticket_quantity) if ticket_quantity and str(ticket_quantity).strip() != "" else None
    ticket_type.ticket_description = data.get('ticket_description', ticket_type.ticket_description)
    ticket_type.ticket_selling_start_date = datetime.datetime.strptime(data.get('ticket_selling_start_date'), '%Y-%m-%d') if data.get('ticket_selling_start_date') else ticket_type.ticket_selling_start_date
    ticket_type.ticket_selling_end_date = datetime.datetime.strptime(data.get('ticket_selling_end_date'), '%Y-%m-%d') if data.get('ticket_selling_end_date') else ticket_type.ticket_selling_end_date
    ticket_type.is_active = data.get('is_active', ticket_type.is_active)

    db.session.commit()
    return jsonify({'message': 'Ticket updated successfully'}), 200

@app.route('/tickets/organizer/delete/<int:ticket_type_id>', methods=['DELETE'])
@login_required
def delete_ticket(ticket_type_id):
    ticket_type = db.session.get(TicketsOrganizers, ticket_type_id)
    if not ticket_type:
        return jsonify({'message': 'Ticket not found'}), 404
    if ticket_type.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403

    db.session.delete(ticket_type)
    db.session.commit()
    return jsonify({'message': 'Ticket deleted successfully'}), 200

@app.route('/tickets/organizer/<int:event_id>/paid', methods=['GET', 'POST'])
def get_paid_tickets(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404

    is_organizer = current_user.is_authenticated and event.organizers_id == current_user.id
    active_team_admin = get_active_team_member(event_id, allowed_roles=['admin'])

    if not is_organizer and not active_team_admin:
        return jsonify({'message': 'Unauthorized'}), 403

    if request.method == 'POST':
        paid_tickets = TicketsUsers.query.filter_by(event_id=event_id, is_successful=True).all()

        tickets_data = []
        for ticket in paid_tickets:
            tickets_data.append({
                'ticket_id': ticket.ticket_id,
                'user_email': ticket.user_email,
                'ticket_type': ticket.ticket_type,
                'ticket_name': ticket.ticket_name,
                'purchase_date': ticket.purchase_date.isoformat() if ticket.purchase_date else None,
                'is_used': ticket.is_used,
                'is_admin_issued': getattr(ticket, 'is_admin_issued', False)
            })

        number_of_tickets_sold = len(paid_tickets)
        breakdown = {}
        admin_issued_count = 0
        admin_issued_types = {}
        for ticket in paid_tickets:
            if getattr(ticket, 'is_admin_issued', False):
                admin_issued_count += 1
                admin_issued_types[ticket.ticket_type] = admin_issued_types.get(ticket.ticket_type, 0) + 1
                continue
            key = (ticket.ticket_type, ticket.ticket_price)
            breakdown[key] = breakdown.get(key, 0) + 1
        number_of_each_ticket_type_sold = [
            {'ticket_type': t, 'ticket_price': price, 'count': count}
            for (t, price), count in sorted(breakdown.items(), key=lambda kv: -kv[1])
        ]

        total_revenue = sum(t.ticket_price for t in paid_tickets if not getattr(t, 'is_admin_issued', False))
        gateo_fee = total_revenue * 0.05
        net_revenue = total_revenue - gateo_fee

        return jsonify({'paid_tickets': tickets_data, 'number_of_tickets_sold': number_of_tickets_sold, 'number_of_each_ticket_type_sold': number_of_each_ticket_type_sold, 'admin_issued_count': admin_issued_count, 'admin_issued_types': admin_issued_types, 'total_revenue': total_revenue, 'gateo_fee': gateo_fee, 'net_revenue': net_revenue}), 200
    
    # Enrich ticket types with status for the issuance modal
    from datetime import datetime
    now = datetime.now()
    for t in event.TicketsOrganizers:
        t.sold_count = TicketsUsers.query.filter_by(event_id=event_id, ticket_type_id=t.ticket_type_id, is_successful=True).count()
        t.is_sold_out = (t.sold_count >= t.ticket_quantity) if t.ticket_quantity is not None else False
        t.is_expired = bool(event.event_end_date) and now >= event.event_end_date

    return render_template('paid_tickets.html', event=event, is_organizer=is_organizer)


@app.route('/tickets/organizer/<int:event_id>/organiser-issued', methods=['POST'])
@login_required
def create_organizer_issued_ticket(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403
    
    

    data = request.get_json() or {}
    user_email = data.get('user_email')
    ticket_type = data.get('ticket_type')
    ticket_name = data.get('ticket_name')
    try:
        ticket_quantity = int(data.get('ticket_quantity', 1))
    except (TypeError, ValueError):
        return jsonify({'message': 'Invalid ticket quantity'}), 400

    if getattr(event, 'is_suspended', False):
        return jsonify({'message': 'Event is currently suspended.'}), 403

    if ticket_quantity < 1:
        return jsonify({'message': 'Quantity must be at least 1'}), 400
    if ticket_quantity > 5:
        return jsonify({'message': 'You can issue at most 5 tickets at once'}), 400

    ticket_type_obj = next((t for t in event.TicketsOrganizers if t.ticket_type == ticket_type), None)
    if not ticket_type_obj:
        return jsonify({'message': 'Invalid ticket type'}), 400
    
    if not ticket_type_obj.is_active:
        return jsonify({'message': 'Ticket type is not available right now'}), 400
    
    from datetime import datetime
    if event.event_end_date and datetime.now() >= event.event_end_date:
        return jsonify({'message': 'Ticket sales have ended'}), 400
    
    if ticket_type_obj.ticket_quantity is not None:
        tickets_sold = TicketsUsers.query.filter_by(event_id=event_id, ticket_type_id=ticket_type_obj.ticket_type_id, is_successful=True).count()
        if tickets_sold + ticket_quantity > ticket_type_obj.ticket_quantity:
            return jsonify({'message': 'Ticket type is sold out'}), 400

    if not user_email or not ticket_type or not ticket_name:
        return jsonify({'message': 'Missing required fields'}), 400

    existing_email_tickets = TicketsUsers.query.filter_by(
        event_id=event_id,
        user_email=user_email,
        is_successful=True
    ).count()
    if existing_email_tickets + ticket_quantity > 10:
        return jsonify({'message': 'Cannot issue more than 10 tickets to one email for this event'}), 400
    
    ticket_type_obj = TicketsOrganizers.query.filter_by(event_id=event_id,ticket_type=ticket_type).first()

    if not ticket_type_obj:
        return jsonify({'message': 'Ticket type not found'}), 400

    ticket_type_id = ticket_type_obj.ticket_type_id
    try:
        created_tickets = []
        for _ in range(ticket_quantity):
            ticket_data = generate_qr_ticket(event_id=event_id, user_email=user_email, ticket_type=ticket_type, ticket_name=ticket_name)
            new_ticket = TicketsUsers(
                event_id=event_id,
                ticket_unique_id=ticket_data['ticket_code'],
                user_email=user_email,
                ticket_type_id=ticket_type_id,
                ticket_type=ticket_type,
                ticket_price=ticket_type_obj.ticket_price,
                ticket_quantity=1,
                ticket_name=ticket_name,
                organizers_id=current_user.id,
                is_successful=True,
                is_free=False,
                is_used=False,
                is_admin_issued=True
            )
            db.session.add(new_ticket)
            created_tickets.append(ticket_data)
        db.session.commit()
        
        
        try:
            send_ticket_email_flask(to_email=user_email, tickets=created_tickets, event_name=event.event_name)
            send_purchase_notification_organiser_issued_ticket(organiser_email=current_user.email, event_name=event.event_name, ticket_type=ticket_type,ticket_name=ticket_name, ticket_quantity=ticket_quantity)
        except Exception as e:
            import traceback
            error_msg = traceback.format_exc()
            print(error_msg)
        return jsonify({'message': f'{ticket_quantity} organizer-issued ticket(s) created successfully'}), 201

    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(error_msg)
        return jsonify({'message': f'Server Error: {str(e)}', 'traceback': error_msg}), 500


@app.route('/tickets/organizer/<int:event_id>/scanner', methods=['GET'])

def scanner_page(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404
    is_organizer = current_user.is_authenticated and event.organizers_id == current_user.id
    active_team_member = get_active_team_member(event_id)

    if not is_organizer and not active_team_member:
        return jsonify({'message': 'Unauthorized'}), 403

    back_url = url_for('manage_event', slug=event.event_slug) if is_organizer else None
    if active_team_member and active_team_member.role == 'admin':
        back_url = url_for('get_paid_tickets', event_id=event_id)

    return render_template('scanner.html', event=event, back_url=back_url)


@app.route('/api/verify_ticket/<int:event_id>', methods=['GET', 'POST'])
def verify_code(event_id):
    if request.method == 'POST':
        event = db.session.get(Events, event_id)
        if not event:
            return jsonify({'message': 'Event not found'}), 404
        is_organizer = current_user.is_authenticated and event.organizers_id == current_user.id
        active_team_member = get_active_team_member(event_id)

        if not is_organizer and not active_team_member:
            return jsonify({'message': 'Unauthorized'}), 403
        if getattr(event, 'is_suspended', False):
            return jsonify({'message': 'Event is temporarily suspended. Scanning is paused.'}), 403
            
        from datetime import date
        if event.event_date and date.today() < event.event_date.date():
            formatted_date = event.event_date.strftime("%d %b %Y")
            return jsonify({'message': f'Check-in is locked until {formatted_date}'}), 403
        if event.event_end_date and datetime.datetime.now() >= event.event_end_date:
            return jsonify({'message': 'Event has ended. Check-in is closed.'}), 403
        data = request.get_json()
        raw_code = data.get('ticket_code', '')
        
        # Extract the pure ticket_code UUID if the QR scanner captured the full gateway URL
        if '/' in raw_code:
            ticket_code_clean = raw_code.rstrip('/').split('/')[-1]
        else:
            ticket_code_clean = raw_code

        ticket = TicketsUsers.query.filter_by(ticket_unique_id=ticket_code_clean).first()
        if not ticket:
            return jsonify({'message': 'Invalid ticket code'}), 404
        if ticket.is_used:
            return jsonify({'message': 'Ticket has already been used'}), 400
        if ticket.event_id != event_id:
            return jsonify({'message': 'invalid ticket'}), 400
        
        event_name = event.event_name
        ticket_type = ticket.ticket_type
        ticket_name = ticket.ticket_name
        ticket.is_used = True
        db.session.commit()
        return jsonify({'message': 'Ticket is valid', 'event_name': event_name, 'ticket_type': ticket_type, 'ticket_name': ticket_name}), 200





@app.route('/e/<string:slug>')
def view_public_event(slug):
    particular_event = Events.query.filter_by(event_slug=slug).first()

    if not particular_event:
        return "Event not found", 404

    ticket_details = TicketsOrganizers.query.filter_by(event_id=particular_event.event_id).order_by(TicketsOrganizers.ticket_price.desc()).all()
    
    # Enrich tickets with calculated statuses
    from datetime import datetime
    now = datetime.now()
    for t in ticket_details:
        t.sold_count = TicketsUsers.query.filter_by(event_id=particular_event.event_id, ticket_type_id=t.ticket_type_id, is_successful=True).count()
        t.is_sold_out = (t.sold_count >= t.ticket_quantity) if t.ticket_quantity is not None else False
        t.is_expired = bool(particular_event.event_end_date) and now >= particular_event.event_end_date
        t.available_quantity = max(0, min((t.ticket_quantity - t.sold_count) if t.ticket_quantity is not None else 5, 5))

    # Fetch media for banner
    event_media = Event_Media.query.filter_by(event_id=particular_event.event_id).all()
    banner = next((m for m in event_media if not m.filepath.lower().endswith(('.mp4', '.mov', '.avi', '.webm'))), None)
    banner_path = banner.filepath if banner else None

    public_back_url = url_for('dashboard')
    public_back_label = 'Dashboard'
    if current_user.is_authenticated and current_user.id == particular_event.organizers_id:
        if request.args.get('from') == 'event_management':
            public_back_url = url_for('manage_event', slug=particular_event.event_slug)
            public_back_label = 'Event Management'

    return render_template('public_event.html', 
                          event=particular_event, 
                          ticket_details=ticket_details,
                          event_media=event_media,
                          banner_path=banner_path,
                          public_back_url=public_back_url,
                          public_back_label=public_back_label,
                          paystack_test_public_key=PAYSTACK_PUBLIC_KEY,
                          organizer_name=db.session.get(Organizers, particular_event.organizers_id).username if particular_event.organizers_id else None)


@app.route('/event/<string:slug>/manage')
@login_required
def manage_event(slug):
    particular_event = Events.query.filter_by(event_slug=slug).first()

    if not particular_event:
        return "Event not found", 404
    if particular_event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403
    if particular_event.is_cancelled:
        return "Event not found", 404

    event_media = Event_Media.query.filter_by(event_id=particular_event.event_id).all()
    banner = next((m for m in event_media if not m.filepath.lower().endswith(('.mp4', '.mov', '.avi', '.webm'))), None)
    if not banner and event_media:
        banner = event_media[0]

    banner_path = banner.filepath if banner else None
    banner_id = banner.media_id if banner else None

    has_sold_tickets = TicketsUsers.query.filter_by(event_id=particular_event.event_id, is_successful=True).first() is not None
    has_withdrawal = Withdrawals.query.filter_by(event_id=particular_event.event_id).first() is not None

    return render_template('event_management.html',
                          event=particular_event,
                          event_media=event_media,
                          banner_path=banner_path,
                          banner_id=banner_id,
                          has_sold_tickets=has_sold_tickets,
                          has_withdrawal=has_withdrawal,
                          paystack_test_public_key=PAYSTACK_PUBLIC_KEY)


@app.route('/event/<string:slug>')
@login_required
def legacy_manage_event(slug):
    return redirect(url_for('manage_event', slug=slug))

@app.route('/ticket/search/<int:event_id>', methods=['GET'])
def search_ticket(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404

    is_organizer = current_user.is_authenticated and event.organizers_id == current_user.id
    active_team_admin = get_active_team_member(event_id, allowed_roles=['admin'])

    if not is_organizer and not active_team_admin:
        return jsonify({'message': 'Unauthorized'}), 403
    
    search = request.args.get('search', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)

    query = TicketsUsers.query.filter_by(event_id=event_id)
    if search:
        query = query.filter(
            TicketsUsers.user_email.ilike(f'%{search}%') |
            TicketsUsers.ticket_type.ilike(f'%{search}%') |
            TicketsUsers.ticket_name.ilike(f'%{search}%')
        )
    tickets = query.paginate(page=page, per_page=limit, error_out=False)
    return jsonify({
        'tickets': [
            {
                'ticket_id': t.ticket_id,
                'ticket_unique_id': t.ticket_unique_id,
                'user_email': t.user_email,
                'ticket_type': t.ticket_type,
                'ticket_name': t.ticket_name,
                'ticket_price': t.ticket_price,
                'is_successful': t.is_successful,
                'is_free': t.is_free,
                'purchase_date': t.purchase_date.isoformat() if t.purchase_date else None,
                'is_used': t.is_used,
                'is_admin_issued': t.is_admin_issued
            } for t in tickets.items
        ],
        'total': tickets.total,
        'page': tickets.page,
        'per_page': tickets.per_page,
        'pages': tickets.pages
    }) 

@app.route('/team/google/auth/<int:event_id>', methods=['GET'])
def team_google_login(event_id):
    
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message':'event not found'}), 404

    session.permanent = True
    session.pop('team_member', None)
    session['team_auth_event_id'] = event_id

    redirect_uri = url_for(
        'team_google_callback',
        _external=True
    )

    return google.authorize_redirect(redirect_uri)

@app.route('/team/google/callback')
def team_google_callback():

    event_id = session.pop('team_auth_event_id', None)

    if not event_id:
        return jsonify({'message':'expired session or invalid event'}), 404

    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message':'event not found'}), 404

    try:
        token = google.authorize_access_token()
    except:
        return jsonify({'message':'Authentication failed'}), 401

    user_info = token.get('userinfo')

    email = user_info['email']

    member = TeamMember.query.filter_by(email=email, event_id=event_id).first()
    
    if not member:
        return jsonify({'message':'Unauthorized'}), 403

    set_team_member_session(member, event_id)
    return redirect_team_member_by_role(member.role, event_id)



@app.route('/team', methods=['GET'])
@login_required
def team_events():
    events = Events.query.filter_by(organizers_id=current_user.id, is_cancelled=False).order_by(Events.event_creation_date.desc()).all()

    return render_template('team_events.html', events=events)


@app.route('/organizer/<int:event_id>/team', methods=['GET'])
@login_required
def manage_team(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message':'event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403

    team_members = TeamMember.query.filter_by(event_id=event_id).order_by(TeamMember.created_at.desc()).all()
    if request.args.get('from') == 'event_management':
        back_url = url_for('manage_event', slug=event.event_slug)
        back_label = 'Event Management'
    else:
        back_url = url_for('team_events')
        back_label = 'Team'

    return render_template('team_manage.html', event=event, team_members=team_members, back_url=back_url, back_label=back_label)


@app.route('/organizer/<int:event_id>/team/create', methods=['POST'])
@login_required
def create_team(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message':'event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403
    data = request.get_json()
    user_email = data.get('user_email')
    role = data.get('role')
    

    if not all([user_email, role]):
        return jsonify({'message': 'All fields are required'}), 400

    allowed_roles = ['admin', 'team_member']

    if role not in allowed_roles:
        return jsonify({'message':'invalid authority'}), 403


    existing_member = TeamMember.query.filter_by(event_id=event_id, email=user_email).first()
    if existing_member:
        return jsonify({'message':'This email is already on the event team'}), 400

    new_team_member= TeamMember(event_id=event_id, email=user_email, role=role,organzier_id=current_user.id)
    db.session.add(new_team_member)
    db.session.commit()

    #send email to the new team member
    
    team_member_login_link = url_for('team_google_login', event_id=event_id, _external=True)
    email_sent = send_collaboration_request(
        new_team_member.email,
        event.event_name,
        new_team_member.role,
        team_member_login_link=team_member_login_link
    )

    if not email_sent:
        return jsonify({
            'message': 'Team member added, but the invitation email failed to send. Check the server logs for the mail error.'
        }), 202

    return jsonify({'message': 'Team member added successfully'}), 201




@app.route('/organizer/<int:event_id>/team/delete/<int:team_id>', methods=['POST'])
@login_required
def organiser_remove_team_member(event_id, team_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'event not found'}), 404
    if event.organizers_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403

    team_member = TeamMember.query.filter_by(event_id=event_id, team_id=team_id).first()
    if not team_member:
        return jsonify({'message': 'team member not found'}), 404

    db.session.delete(team_member)
    db.session.commit()
    return jsonify({'message': 'Team member removed successfully'}), 200
















@app.route('/api/initialize_ticket_purchase/<int:event_id>', methods= ['POST'])
def initialize_ticket_purchase(event_id):
    event = db.session.get(Events, event_id)
    organizer_id = event.organizers_id
    organizer = db.session.get(Organizers, organizer_id)
    organizer_email = organizer.email

    if not event:
        return jsonify({'message':'event not found'}), 404
    data = request.get_json() or {}
    purchase_ticket_type = data.get('ticket_type')
    user_email = data.get('user_email')
    user_name = data.get('user_name')
    
    try:
        purchase_quantity = int(data.get('quantity', 1))
    except (TypeError, ValueError):
        return jsonify({'message': 'Invalid quantity'}), 400
    
    

    if not all([purchase_ticket_type, user_email, user_name]):
        return jsonify({'message': 'All fields are required'}), 400
    
    if purchase_quantity < 1:
        return jsonify({'message': 'Quantity must be at least 1'}), 400
    
    if purchase_quantity > 5:
        return jsonify({'message' : "one email can't purchase more than 5 tickets at once"}), 400
    
    check_email_purchase_quantity = TicketsUsers.query.filter_by(event_id=event_id, user_email=user_email,  is_successful=True).count()
    if check_email_purchase_quantity + purchase_quantity > 5:
        return jsonify({'message' : "one email can't purchase more than 5 tickets with an email"}), 400

    ticket_type = TicketsOrganizers.query.filter_by(event_id=event_id,ticket_type=purchase_ticket_type).first()
    if not ticket_type:
        return jsonify({'message':'ticket type not found'}), 404
    if getattr(event, 'is_suspended', False):
        return jsonify({'message': 'Event is not currently selling tickets'}), 403
    if not ticket_type.is_active:
        return jsonify({'message': 'Ticket type is not available right now'}), 400
    
    ticket_type_id = ticket_type.ticket_type_id

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
    stale = TicketsUsers.query.filter(
        TicketsUsers.event_id == event_id,
        TicketsUsers.ticket_type_id == ticket_type_id,
        TicketsUsers.is_successful == False,
        TicketsUsers.purchase_date < cutoff
    ).all()
    if stale:
        for t in stale:
            db.session.delete(t)
        db.session.commit()

    sold_tickets = TicketsUsers.query.filter_by(event_id=event_id, ticket_type_id=ticket_type_id, is_successful=True).count()
    total_tickets = ticket_type.ticket_quantity if ticket_type.ticket_quantity is not None else float('inf')
    remaining_tickets = total_tickets - sold_tickets
    
    
    if remaining_tickets < purchase_quantity:
        return jsonify({'message': 'Not enough tickets available'}), 400

    if event.is_cancelled:
        return jsonify({'message': 'This event has been cancelled.'}), 400

    if event.event_end_date and datetime.datetime.now() >= event.event_end_date:
        return jsonify({'message': 'Ticket sales have ended'}), 400

    GATEOS_PURCHASE_LEVY = 100
    ticket_subtotal = (ticket_type.ticket_price or 0) * purchase_quantity
    user_checkout_amount = ticket_subtotal + GATEOS_PURCHASE_LEVY
    user_checkout_amount_in_kobo = int(user_checkout_amount * 100)
    reference_code = f"GATEO_{event.event_slug}{uuid.uuid4().hex[:12]}"

    if ticket_subtotal <= 0:
        created_tickets = []
        for _ in range(purchase_quantity):
            ticket_data = generate_qr_ticket(
                event_id=event.event_id,
                user_email=user_email,
                ticket_type=ticket_type.ticket_type,
                ticket_name=user_name
            )
            new_ticket = TicketsUsers(
                event_id=event.event_id,
                ticket_unique_id=ticket_data['ticket_code'],
                user_email=user_email,
                ticket_type_id=ticket_type.ticket_type_id,
                ticket_type=ticket_type.ticket_type,
                ticket_price=0,
                ticket_quantity=1,
                ticket_name=user_name,
                organizers_id=event.organizers_id,
                is_successful=True,
                is_free=True,
                is_used=False,
                is_admin_issued=False,
                payment_reference=reference_code
            )
            db.session.add(new_ticket)
            created_tickets.append(ticket_data)

        db.session.commit()

        try:
            send_ticket_email_flask(
                to_email=user_email,
                tickets=created_tickets,
                event_name=event.event_name
            )
        except Exception:
            pass

        try:
            send_purchase_notification_to_organiser(
                organiser_email=organizer_email,
                event_name=event.event_name,
                ticket_type=ticket_type.ticket_type,
                ticket_name=user_name,
                ticket_quantity=purchase_quantity
            )
        except Exception:
            pass





        return jsonify({
            'message': 'Ticket generated and sent to your email',
            'requires_payment': False,
            'reference': reference_code
        }), 200

    #set up paystack
    headers = {
    "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json"
}

    payload = {
    "email": user_email,
    "amount": user_checkout_amount_in_kobo,
    "reference": reference_code,
        "callback_url": f"{request.host_url}e/{event.event_slug}?payment=success",
    "metadata": {
        "event_id": event.event_id,
        "ticket_type_id": ticket_type.ticket_type_id,
        "ticket_type": ticket_type.ticket_type,
        "quantity": purchase_quantity,
        "buyer_name": user_name
    }
}

    response = requests.post(
    "https://api.paystack.co/transaction/initialize",
    headers=headers,
    json=payload
)


    if response.status_code != 200:
        return jsonify({
        "message": "Unable to initialize payment."
    }), 500

    paystack_response = response.json()

    if not paystack_response.get("status"):
        return jsonify({
        "message": paystack_response.get("message")
    }), 400


    new_ticket = TicketsUsers(
        event_id=event.event_id,
        ticket_unique_id=None,
        user_email=user_email,
        ticket_type_id=ticket_type.ticket_type_id,
        ticket_type=ticket_type.ticket_type,
        ticket_price=ticket_type.ticket_price,
        ticket_quantity=purchase_quantity,
        ticket_name=user_name,
        organizers_id=event.organizers_id,
        is_successful=False,
        is_free=False,
        is_used=False,
        is_admin_issued=False,
        payment_reference=reference_code
    )

    db.session.add(new_ticket)
    db.session.commit()

    return jsonify({
    "requires_payment": True,
    "authorization_url": paystack_response["data"]["authorization_url"],
    "reference": reference_code
    }), 200

    




@app.route('/api/payment_status/<reference>')
def payment_status(reference):
    payment = TicketsUsers.query.filter_by(payment_reference=reference).first()
    if not payment:
        return jsonify({"status": "not_found"}), 404
    if payment.is_successful:
        return jsonify({"status": "confirmed"})
    return jsonify({"status": "pending"})


@app.route('/api/paystack/webhook', methods=['POST'])
def paystack_webhook():



    signature = request.headers.get("x-paystack-signature")

    computed_signature = hmac.new(
        PAYSTACK_SECRET_KEY.encode(),
        request.data,
        hashlib.sha512
    ).hexdigest()

    if not signature or not hmac.compare_digest(signature, computed_signature):
        return jsonify({"message": "Invalid signature"}), 401

    payload = request.get_json()

    if not payload:
        return jsonify({"message": "Invalid payload"}), 400

    # -----------------------------
    # 2. Route by event type
    # -----------------------------
    event_type = payload.get("event")
    data = payload.get("data", {})

    # -----------------------------
    # Transfer events (withdrawals)
    # -----------------------------
    if event_type in ("transfer.success", "transfer.failed", "transfer.reversed"):
        transfer_ref = data.get("reference")

        if not transfer_ref:
            return jsonify({"message": "Missing transfer reference"}), 400

        withdrawal = Withdrawals.query.filter_by(paystack_transfer_ref=transfer_ref).first()
        if not withdrawal:
            return jsonify({"message": "Withdrawal not found"}), 404

        if event_type == "transfer.success":
            withdrawal.status = "successful"

            event = db.session.get(Events, withdrawal.event_id)
            organizer = db.session.get(Organizers, withdrawal.organizer_id)
            if event and organizer:
                try:
                    send_withdrawal_success_email(
                        organizer_email=organizer.email,
                        event_name=event.event_name,
                        amount=withdrawal.amount or 0,
                        account_name=withdrawal.account_name or '',
                        bank_name=withdrawal.bank_name or '',
                        account_number=withdrawal.account_number or '',
                    )
                except Exception:
                    pass

        elif event_type == "transfer.failed":
            withdrawal.status = "failed"
        elif event_type == "transfer.reversed":
            withdrawal.status = "reversed"

        db.session.commit()

        return jsonify({"message": f"Transfer {withdrawal.status}"}), 200

    # -----------------------------
    # 3. Ignore unrelated events
    # -----------------------------
    if event_type != "charge.success":
        return jsonify({"message": "Ignored"}), 200

    reference = data.get("reference")

    if not reference:
        return jsonify({"message": "Missing reference"}), 400

    # -----------------------------
    # 3. Verify transaction
    # -----------------------------
    try:
        verify_response = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
            },
            timeout=30
        )
    except requests.RequestException:
        return jsonify({"message": "Unable to reach Paystack for verification"}), 503

    if verify_response.status_code != 200:
        return jsonify({"message": "Unable to verify payment"}), 400

    try:
        verification = verify_response.json()
    except ValueError:
        return jsonify({"message": "Invalid response from Paystack"}), 400

    if not verification.get("status"):
        return jsonify({"message": "Verification failed"}), 400

    payment_data = verification.get("data") or {}

    if payment_data.get("status") != "success":
        return jsonify({"message": "Payment not successful"}), 400

    # -----------------------------
    # 4. Retrieve pending payment
    # -----------------------------
    payment = TicketsUsers.query.filter_by(
        payment_reference=reference
    ).first()

    if not payment:
        return jsonify({"message": "Payment not found"}), 404

    # -----------------------------
    # 5. Prevent duplicate processing
    # -----------------------------
    if payment.is_successful:
        return jsonify({"message": "Already processed"}), 200

    # -----------------------------
    # 6. Update payment
    # -----------------------------
    payment.is_successful = True


    db.session.commit()

    # -----------------------------
    # 7. Retrieve related objects
    # -----------------------------
    event = db.session.get(Events, payment.event_id)
    if not event:
        return jsonify({"message": "Event not found"}), 404

    ticket_type = db.session.get(
        TicketsOrganizers,
        payment.ticket_type_id
    )
    if not ticket_type:
        return jsonify({"message": "Ticket type not found"}), 404

    organizer = db.session.get(
        Organizers,
        event.organizers_id
    )
    if not organizer:
        return jsonify({"message": "Organizer not found"}), 404

    created_tickets = []

    # -----------------------------
    # 8. Generate purchased tickets
    # -----------------------------
    try:
        for _ in range(payment.ticket_quantity):

            ticket_data = generate_qr_ticket(
                event_id=event.event_id,
                user_email=payment.user_email,
                ticket_type=ticket_type.ticket_type,
                ticket_name=payment.ticket_name
            )

            ticket = TicketsUsers(
                event_id=event.event_id,
                ticket_unique_id=ticket_data["ticket_code"],
                user_email=payment.user_email,
                ticket_type_id=ticket_type.ticket_type_id,
                ticket_type=ticket_type.ticket_type,
                ticket_price=ticket_type.ticket_price,
                ticket_quantity=1,
                ticket_name=payment.ticket_name,
                organizers_id=event.organizers_id,
                is_successful=True,
                is_free=False,
                is_used=False,
                is_admin_issued=False,
                payment_reference=reference
            )

            db.session.add(ticket)

            created_tickets.append(ticket_data)

        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Ticket generation failed"}), 500

    # -----------------------------
    # 9. Send ticket email
    # -----------------------------
    try:
        send_ticket_email_flask(
            to_email=payment.user_email,
            tickets=created_tickets,
            event_name=event.event_name

        )
    except Exception:
        pass

    # -----------------------------
    # 10. Notify organiser
    # -----------------------------
    try:
        send_purchase_notification_to_organiser(
            organiser_email=organizer.email,
            event_name=event.event_name,
            ticket_type=ticket_type.ticket_type,
            ticket_name=payment.ticket_name,
            ticket_quantity=payment.ticket_quantity,
            ticket_price=ticket_type.ticket_price
        )
    except Exception:
        pass

    return jsonify({"message": "Webhook processed"}), 200



# setting up cashier

@app.route('/cashier', methods=['GET'])
def cashier():
   
    organizer_id = current_user.id

    events = db.session.query(Events).filter_by(organizers_id=organizer_id, is_cancelled=False).order_by(Events.event_creation_date.desc()).all()

    events_data = []
    for event in events:
        sales = db.session.query(TicketsUsers).filter_by(event_id=event.event_id, is_successful=True, is_admin_issued=False)
        Total_Revenue = 0
        for sale in sales:
            ticket_price = sale.ticket_price
            Total_Revenue += ticket_price

        Gateo_percentage = 6
        withdrawable_percentage= 50

        Gateo_fee = Total_Revenue * (Gateo_percentage/100)
        organizer_revenue = Total_Revenue - Gateo_fee
        withdrawable_before_event= organizer_revenue/2
        
        


    
        media = db.session.query(Event_Media).filter_by(event_id=event.event_id).first()
        events_data.append({

            'event_id': event.event_id,
            'event_name': event.event_name,
            'event_date': event.event_date.strftime('%Y-%m-%d') if event.event_date else None,
            'event_time': event.event_time.strftime('%H:%M:%S') if event.event_time else None,
            'organizers_id': event.organizers_id,
            'event_creation_date': event.event_creation_date.isoformat() if event.event_creation_date else None,
            'event_end_date': event.event_end_date.isoformat() if event.event_end_date else None,

            'media': get_media_url(media.filepath) if media else None,
            'Total_Revenue': Total_Revenue,
            'withdrawable_revenue': organizer_revenue if event_full_withdrawal_datetime(event) and datetime.datetime.now() >= event_full_withdrawal_datetime(event) else withdrawable_before_event

    })

    withdrawals = Withdrawals.query.filter_by(
        organizer_id=organizer_id
    ).order_by(Withdrawals.created_at.desc()).all()

    withdrawal_history = []
    for w in withdrawals:
        event_obj = db.session.get(Events, w.event_id)
        withdrawal_history.append({
            'id': w.id,
            'event_name': event_obj.event_name if event_obj else 'Unknown Event',
            'amount': w.amount,
            'bank_name': w.bank_name,
            'account_number': w.account_number,
            'account_name': w.account_name,
            'status': w.status,
            'created_at': w.created_at.strftime('%d %b %Y, %I:%M %p') if w.created_at else None,
        })

    return render_template('cashier.html', event=events_data, withdrawal_history=withdrawal_history)

@app.route('/cashier/send_withdrawal_link/<int:event_id>', methods=['POST'])
@login_required
def withdrawal_link(event_id):
    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'event not found'}), 404

    if current_user.id != event.organizers_id:
        return jsonify({'message': 'user is not authorized'}), 401
    
    if getattr(event, 'date_location_changed_at', None):
        window_end = event.date_location_changed_at + datetime.timedelta(days=5)
        if datetime.datetime.utcnow() < window_end:
            return jsonify({'message': 'Withdrawal blocked. A date/location change was recently made. Please wait for the 5-day refund window to close.'}), 403
    
    sales = db.session.query(TicketsUsers).filter_by(event_id=event.event_id, is_successful=True, is_admin_issued=False)
    Total_Revenue = 0
    for sale in sales:
        ticket_price = sale.ticket_price
        Total_Revenue += ticket_price
    if Total_Revenue <= 0:
        return jsonify({'message': 'No revenue to withdraw'}), 400

    existing = Withdrawals.query.filter_by(
        event_id=event_id,
        organizer_id=current_user.id,
        is_used=False
    ).order_by(Withdrawals.created_at.desc()).first()

    if existing:
        token_age = datetime.datetime.utcnow() - existing.created_at
        if token_age < datetime.timedelta(minutes=5):
            organizer_email = db.session.get(Organizers, event.organizers_id).email
            send_withdrawal_link(
                organizer_email=organizer_email,
                event_name=event.event_name,
                organizer_id=current_user.id,
                event_id=event_id,
                base_url=request.host_url,
                token=existing.token
            )
            return jsonify({'message': 'Withdrawal link sent'}), 200

    token = secrets.token_urlsafe(32)
    withdrawal = Withdrawals(
        token=token,
        organizer_id=current_user.id,
        event_id=event_id
    )
    db.session.add(withdrawal)
    db.session.commit()

    organizer_email = db.session.get(Organizers, event.organizers_id).email
    event_name = event.event_name

    sent = send_withdrawal_link(organizer_email=organizer_email,event_name=event_name,organizer_id=current_user.id,event_id=event_id,base_url=request.host_url,token=token)
    if not sent:
        return jsonify({'message': 'Failed to send withdrawal link'}), 500
    return jsonify({'message': 'Withdrawal link sent'}), 200


@app.route('/cashier/withdrawal/<int:organizer_id>/<int:event_id>', methods=['GET'])
def withdrawal_dashboard(organizer_id, event_id):
    
    token = request.args.get('token')
    if not token:
        return render_template('expired_link.html', message='Invalid withdrawal link'), 400

    withdrawal = Withdrawals.query.filter_by(token=token).first()
    if not withdrawal:
        return render_template('expired_link.html', message='Invalid withdrawal link'), 400

    if withdrawal.is_used:
        return render_template('expired_link.html', message='This link has already been used'), 400

    token_age = datetime.datetime.utcnow() - withdrawal.created_at
    if token_age > datetime.timedelta(minutes=5):
        return render_template('expired_link.html', message='This link has expired'), 400

    if withdrawal.organizer_id != organizer_id or withdrawal.event_id != event_id:
        return render_template('expired_link.html', message='Invalid withdrawal link'), 400

    event = db.session.get(Events, event_id)
    if not event:
        return render_template('expired_link.html', message='Event not found'), 404
    if event.organizers_id != organizer_id:
        return render_template('expired_link.html', message='Unauthorized'), 401
    
    tickets = db.session.query(TicketsUsers).filter_by(event_id=event.event_id, is_successful=True, is_admin_issued=False)
    Total_Revenue = 0

    for ticket in tickets:
        ticket_price = ticket.ticket_price
        Total_Revenue += ticket_price

    Gateo_percentage = 6

    Gateo_fee = Total_Revenue * (Gateo_percentage/100)
    organizer_revenue = Total_Revenue - Gateo_fee
    withdrawable_before_event= organizer_revenue/2

    media = db.session.query(Event_Media).filter_by(event_id=event.event_id).first()
    event_data = ({
        'event_id': event.event_id,
        'event_name': event.event_name,
        'event_date': event.event_date.strftime('%Y-%m-%d') if event.event_date else None,
        'event_time': event.event_time.strftime('%H:%M:%S') if event.event_time else None,
        'organizers_id': event.organizers_id,
        'event_end_date': event.event_end_date.isoformat() if event.event_end_date else None,
        'media': get_media_url(media.filepath) if media else None,
        'Total_Revenue': Total_Revenue,
        'withdrawable_revenue': organizer_revenue if event_full_withdrawal_datetime(event) and datetime.datetime.now() >= event_full_withdrawal_datetime(event) else withdrawable_before_event
        })

    return render_template('withdrawal_dashboard.html', organizer_username=db.session.get(Organizers, organizer_id).username, event_data=event_data, token=token)

@app.route('/cashier/withdrawal/<int:organizer_id>/<int:event_id>', methods=['POST'])
def process_withdrawal(organizer_id, event_id):
    data = request.get_json() or {}
    token = data.get('token') or request.args.get('token')
    if not token:
        return jsonify({'message': 'Invalid withdrawal link'}), 400

    withdrawal = Withdrawals.query.filter_by(token=token).first()
    if not withdrawal:
        return jsonify({'message': 'Invalid withdrawal link'}), 400

    if withdrawal.is_used:
        return jsonify({'message': 'This link has already been used'}), 400

    token_age = datetime.datetime.utcnow() - withdrawal.created_at
    if token_age > datetime.timedelta(minutes=5):
        return jsonify({'message': 'This link has expired'}), 400

    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'event not found'}), 404
    if event.organizers_id != organizer_id or withdrawal.organizer_id != organizer_id:
        return jsonify({'message': 'user is not authorized'}), 401

    if getattr(event, 'date_location_changed_at', None):
        window_end = event.date_location_changed_at + datetime.timedelta(days=5)
        if datetime.datetime.utcnow() < window_end:
            return jsonify({'message': 'Withdrawal blocked. A date/location change was recently made. Please wait for the 5-day refund window to close.'}), 403

    bank_name = data.get('bank_name')
    account_number = data.get('account_number')
    amount = data.get('amount')

    if not bank_name or not account_number or not amount:
        return jsonify({'message': 'All fields are required'}), 400

    if len(account_number) != 10 or not account_number.isdigit():
        return jsonify({'message': 'Invalid account number'}), 400

    bank_code = BANK_CODES.get(bank_name)
    if not bank_code:
        return jsonify({'message': 'Invalid bank selected'}), 400

    account, error = resolve_account_paystack(account_number, bank_code)
    if error:
        return jsonify({'message': error}), 400

    tickets = db.session.query(TicketsUsers).filter_by(event_id=event.event_id, is_successful=True, is_admin_issued=False)
    Total_Revenue = 0
    for ticket in tickets:
        Total_Revenue += ticket.ticket_price

    Gateo_fee = Total_Revenue * 0.06
    organizer_revenue = Total_Revenue - Gateo_fee
    withdrawable_before_event = organizer_revenue / 2
    max_withdrawable = organizer_revenue if event_full_withdrawal_datetime(event) and datetime.datetime.now() >= event_full_withdrawal_datetime(event) else withdrawable_before_event

    if amount > max_withdrawable:
        return jsonify({'message': 'Amount exceeds withdrawable balance'}), 400

    if float(amount) > 5000000:
        return jsonify({'message': 'Maximum single withdrawal is ₦5,000,000. Please withdraw in smaller amounts.'}), 400
 
    withdrawal.amount = float(amount)
    withdrawal.bank_name = bank_name
    withdrawal.account_number = account_number
    withdrawal.account_name = account['account_name']
    withdrawal.is_used = True
    withdrawal.status = 'processing'
    db.session.commit()

    try:
        recipient_resp = requests.post(
            'https://api.paystack.co/transferrecipient',
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'},
            json={
                'type': 'nuban',
                'name': account['account_name'],
                'account_number': account_number,
                'bank_code': bank_code,
                'currency': 'NGN'
            },
            timeout=30
        )

        if not recipient_resp.ok:
            return jsonify({'message': 'Failed to create transfer recipient'}), 500

        recipient = recipient_resp.json()

        if not recipient.get('status'):
            return jsonify({'message': recipient.get('message', 'Failed to create transfer recipient')}), 500

        recipient_code = (recipient.get('data') or {}).get('recipient_code')
        if not recipient_code:
            return jsonify({'message': 'Invalid recipient response from Paystack'}), 500

        transfer_resp = requests.post(
            'https://api.paystack.co/transfer',
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'},
            json={
                'source': 'balance',
                'amount': int(float(amount) * 100),
                'recipient': recipient_code,
                'reason': f'Withdrawal for {event.event_name}'
            },
            timeout=30
        )

        if not transfer_resp.ok:
            withdrawal.status = 'failed'
            db.session.commit()
            return jsonify({'message': 'Transfer initiation failed'}), 500

        transfer = transfer_resp.json()

        if not transfer.get('status'):
            withdrawal.status = 'failed'
            db.session.commit()
            return jsonify({'message': transfer.get('message', 'Transfer initiation failed')}), 500

        transfer_data = transfer.get('data') or {}
        transfer_ref = transfer_data.get('reference')

        if not transfer_ref:
            withdrawal.status = 'failed'
            db.session.commit()
            return jsonify({'message': 'Invalid transfer response from Paystack'}), 500

        withdrawal.paystack_recepient_code = recipient_code
        withdrawal.paystack_transfer_ref = transfer_ref
        db.session.commit()

    except Exception:
        withdrawal.status = 'failed'
        db.session.commit()
        return jsonify({'message': 'Payment processing failed'}), 500
    return jsonify({'message': 'Withdrawal request submitted successfully'}), 200


@app.route('/api/resolve-bank-account/<int:event_id>', methods=['POST'])
def resolve_bank_account(event_id):

    event = db.session.get(Events, event_id)
    if not event:
        return jsonify({'message': 'Event not found'}), 404

    data = request.get_json() or {}

    token = data.get('token')
    if token:
        withdrawal = Withdrawals.query.filter_by(token=token).first()
        if not withdrawal or withdrawal.is_used or withdrawal.event_id != event_id:
            return jsonify({'message': 'Invalid or expired withdrawal link'}), 403
        if withdrawal.organizer_id != event.organizers_id:
            return jsonify({'message': 'Unauthorized'}), 403
        token_age = datetime.datetime.utcnow() - withdrawal.created_at
        if token_age > datetime.timedelta(minutes=5):
            return jsonify({'message': 'This link has expired'}), 403
    else:
        if not current_user.is_authenticated or event.organizers_id != current_user.id:
            return jsonify({'message': 'Unauthorized'}), 403

        withdrawal = Withdrawals.query.filter_by(event_id=event_id, organizer_id=current_user.id, is_used=False).first()
        if not withdrawal:
            return jsonify({'message': 'No active withdrawal request found'}), 404

    account_number = data.get('account_number')
    bank_code = data.get('bank_code') or BANK_CODES.get(data.get('bank_name'))

    if not account_number or not bank_code:
        return jsonify({
            'message': 'Account number and bank code are required'
        }), 400

    account, error = resolve_account_paystack(account_number, bank_code)

    if error:
        return jsonify({
            'message': error
        }), 400

    if not account:
        return jsonify({
            'message': 'Unable to verify bank account'
        }), 400

    return jsonify({
        'message': 'Account verified',
        'account_number': account.get('account_number'),
        'account_name': account.get('account_name'),
        'bank_id': account.get('bank_id')
    }), 200





     


    








    

    













    



    













# On startup, ensure the schema exists. db.create_all() only creates
# missing tables/columns for a fresh database; it never alters existing
# tables. For an existing database that was created before the
# is_purchased -> is_successful / is_free rename, run
# `python migrate_tickets_flags.py` once to migrate it in place.

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)











