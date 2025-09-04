from fastapi import FastAPI, HTTPException, Request, Depends
try:
    # Prefer FastAPI's re-export; fallback to Starlette for older FastAPI versions
    from fastapi.middleware.cors import CORSMiddleware  # type: ignore
except Exception:  # pragma: no cover
    from starlette.middleware.cors import CORSMiddleware  # type: ignore
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, text, Boolean, Float, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from datetime import datetime, timedelta
import os
import random
import requests
import stripe
from enum import Enum

# Config via environment variables with sensible defaults for production docker
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DATABASE_URL = os.getenv("DATABASE_URL", f"postgresql://postgres:{POSTGRES_PASSWORD}@postgres:5432/litellm")
LITELLM_URL = os.getenv("LITELLM_URL", "http://litellm:4000")
ADMIN_KEY = os.getenv("ADMIN_KEY")
# Telegram Bot (optional)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7599653806:AAEhw_ISbn76vRY2pd8gxU8lIbNyC0hHBbA")
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.getenv("TELEGRAM_CHAT_IDS", "-4919414883").split(",") if cid.strip()]
# Stripe Config
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
stripe.api_key = STRIPE_SECRET_KEY
# Comma-separated list of allowed frontend origins for CORS
# Example: "http://localhost:5173,http://127.0.0.1:5173,https://yourdomain.com"
FRONTEND_ORIGINS = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,https://demoaiconnex.space",
)
BACKEND_ORIGINS = os.getenv("BACKEND_ORIGINS", "https://aiconnex.space")

# Validate required environment variables
if not ADMIN_KEY:
    raise ValueError("ADMIN_KEY environment variable is required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

app = FastAPI()

# Configure CORS so the Vue dev server can call this API
origins = [origin.strip() for origin in FRONTEND_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if any(o in {"*", "all", "ALL"} for o in origins) else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure schema exists (for Postgres)
def init_database():
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS login"))
        Base.metadata.create_all(bind=engine)
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"⚠️ Database initialization failed: {e}")
        # Don't block app start, will retry on first request


class PhoneOTP(Base):
    __tablename__ = "phone_otp"
    __table_args__ = {"schema": "login"}

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, index=True)
    otp_code = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class PhoneAPIKey(Base):
    __tablename__ = "phone_api_keys"
    __table_args__ = {"schema": "login"}

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    api_key = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to subscription
    subscription = relationship("UserSubscription", back_populates="api_key", uselist=False)


class PlanType(str, Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    PREMIUM = "premium"


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = {"schema": "login"}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)  # free, basic, pro, premium
    price_usd = Column(Float)  # 0, 2, 5, 10
    max_budget = Column(Float)  # Monthly budget limit
    rpm_limit = Column(Integer)  # Requests per minute
    tpm_limit = Column(Integer)  # Tokens per minute
    max_parallel_requests = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = {"schema": "login"}

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, ForeignKey("login.phone_api_keys.phone_number"), unique=True, index=True)
    plan_id = Column(Integer, ForeignKey("login.subscription_plans.id"))
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)  # For non-recurring plans
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    plan = relationship("SubscriptionPlan")
    api_key = relationship("PhoneAPIKey", back_populates="subscription")


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = {"schema": "login"}

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, index=True)
    stripe_payment_intent_id = Column(String, unique=True, index=True)
    stripe_session_id = Column(String, nullable=True)
    amount_usd = Column(Float)
    plan_name = Column(String)
    status = Column(String)  # pending, succeeded, failed, canceled
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Plan configurations
PLAN_CONFIGS = {
    PlanType.FREE: {
        "name": "Free",
        "price_usd": 0.0,
        "max_budget": None,
        "rpm_limit": 2,
        "tpm_limit": 1000,
        "max_parallel_requests": 1
    },
    PlanType.BASIC: {
        "name": "Basic",
        "price_usd": 2.0,
        "max_budget": 2.0,
        "rpm_limit": 10,
        "tpm_limit": 10000,
        "max_parallel_requests": 3
    },
    PlanType.PRO: {
        "name": "Pro", 
        "price_usd": 5.0,
        "max_budget": 5.0,
        "rpm_limit": 50,
        "tpm_limit": 50000,
        "max_parallel_requests": 5
    },
    PlanType.PREMIUM: {
        "name": "Premium",
        "price_usd": 10.0,
        "max_budget": 10.0,
        "rpm_limit": 100,
        "tpm_limit": 100000,
        "max_parallel_requests": 10
    }
}

def init_subscription_plans():
    """Initialize default subscription plans if they don't exist"""
    try:
        db = SessionLocal()
        for plan_type, config in PLAN_CONFIGS.items():
            existing_plan = db.query(SubscriptionPlan).filter_by(name=plan_type.value).first()
            if not existing_plan:
                plan = SubscriptionPlan(
                    name=plan_type.value,
                    price_usd=config["price_usd"],
                    max_budget=config["max_budget"],
                    rpm_limit=config["rpm_limit"],
                    tpm_limit=config["tpm_limit"],
                    max_parallel_requests=config["max_parallel_requests"]
                )
                db.add(plan)
        db.commit()
        db.close()
        print("✅ Subscription plans initialized")
    except Exception as e:
        print(f"⚠️ Failed to initialize subscription plans: {e}")

# Initialize database tables
init_database()
init_subscription_plans()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_or_create_stripe_customer(phone_number: str, db: Session) -> str:
    """Get or create Stripe customer for phone number"""
    subscription = db.query(UserSubscription).filter_by(phone_number=phone_number).first()
    
    if subscription and subscription.stripe_customer_id:
        return subscription.stripe_customer_id
    
    # Create new Stripe customer
    customer = stripe.Customer.create(
        metadata={"phone_number": phone_number}
    )
    
    return customer.id

def update_litellm_api_key(phone_number: str, plan_config: dict, db: Session) -> bool:
    """Update LiteLLM API key limits based on subscription plan"""
    try:
        print(f"🔍 [DEBUG] Checking API key for phone: {phone_number}")
        api_key_entry = db.query(PhoneAPIKey).filter_by(phone_number=phone_number).first()
        if not api_key_entry:
            print(f"❌ [ERROR] No API key found for phone: {phone_number}")
            return False

        print(f"✅ [DEBUG] Found API key: {api_key_entry.api_key[:20]}...")
        
        # Update key via LiteLLM API
        url = f"{LITELLM_URL.rstrip('/')}/key/update"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ADMIN_KEY}"
        }
        
        # Build payload with proper handling of None values
        payload = {
            "key": api_key_entry.api_key,
            "budget_duration": "30d",
            "max_parallel_requests": plan_config["max_parallel_requests"],
            "tpm_limit": plan_config["tpm_limit"],
            "rpm_limit": plan_config["rpm_limit"],
        }
        
        # Only add max_budget if it's not None (for free plan)
        if plan_config["max_budget"] is not None:
            payload["max_budget"] = plan_config["max_budget"]
        
        print(f"🌐 [DEBUG] Calling LiteLLM API: {url}")
        print(f"📦 [DEBUG] Payload: {payload}")
        print(f"🔑 [DEBUG] ADMIN_KEY present: {'Yes' if ADMIN_KEY else 'No'}")
        print(f"🔑 [DEBUG] ADMIN_KEY length: {len(ADMIN_KEY) if ADMIN_KEY else 0}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"📡 [DEBUG] Response status: {response.status_code}")
        print(f"📄 [DEBUG] Response body: {response.text}")
        
        if response.status_code == 200:
            print(f"✅ [SUCCESS] LiteLLM key updated for {phone_number}")
            return True
        else:
            print(f"❌ [ERROR] LiteLLM update failed: {response.status_code} - {response.text}")
            return False
        
    except Exception as e:
        print(f"💥 [EXCEPTION] Error updating LiteLLM key: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


class PhoneRequest(BaseModel):
    phone_number: str


class VerifyRequest(BaseModel):
    phone_number: str
    otp_code: str


class CreateCheckoutRequest(BaseModel):
    phone_number: str
    plan_type: PlanType
    success_url: str
    cancel_url: str




def send_telegram_message(text: str) -> None:
    """
    Send a message to configured Telegram chat(s) using Bot API.

    This is optional; if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_IDS are not set, it does nothing.
    """
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
            return

        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        for chat_id in TELEGRAM_CHAT_IDS:
            try:
                response = requests.post(
                    api_url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
                if response.status_code != 200:
                    print(f"⚠️ Telegram send failed for chat {chat_id}: {response.text}")
            except Exception as inner_e:
                print(f"⚠️ Telegram send error for chat {chat_id}: {inner_e}")
    except Exception as e:
        # Do not block OTP flow due to Telegram issues
        print(f"⚠️ Telegram error: {e}")


def send_sms(phone: str, otp: str) -> None:
    """
    Send SMS OTP to phone number.
    TODO: Implement actual SMS service (Viettel, Twilio, etc.)
    For now, just log to console for development/testing.
    """
    print(f"[SMS] Sending OTP {otp} to {phone}")
    # Also notify via Telegram (optional)
    send_telegram_message(f"<b>OTP</b>: <code>{otp}</code>\n<b>Phone</b>: {phone}\n<i>Valid for 5 minutes</i>")
    # TODO: Replace with actual SMS API call
    # Example with Viettel SMS API:
    # response = requests.post(
    #     "https://api.viettel.com.vn/sms/send",
    #     json={
    #         "phone": phone,
    #         "message": f"Your OTP is: {otp}. Valid for 5 minutes.",
    #         "api_key": os.getenv("SMS_API_KEY")
    #     }
    # )
    # if response.status_code != 200:
    #     raise Exception(f"SMS sending failed: {response.text}")


@app.post("/send-otp")
def send_otp(req: PhoneRequest):
    try:
        db = SessionLocal()
        otp = str(random.randint(100000, 999999))
        expires = datetime.utcnow() + timedelta(minutes=5)

        entry = PhoneOTP(phone_number=req.phone_number, otp_code=otp, expires_at=expires)
        db.add(entry)
        db.commit()

        send_sms(req.phone_number, otp)
        return {"message": "OTP sent"}
    except Exception as e:
        # Try to initialize database if it failed during startup
        try:
            init_database()
            db = SessionLocal()
            otp = str(random.randint(100000, 999999))
            expires = datetime.utcnow() + timedelta(minutes=5)

            entry = PhoneOTP(phone_number=req.phone_number, otp_code=otp, expires_at=expires)
            db.add(entry)
            db.commit()

            send_sms(req.phone_number, otp)
            return {"message": "OTP sent"}
        except Exception as retry_e:
            raise HTTPException(status_code=500, detail=f"Database error: {retry_e}")


@app.post("/verify-otp")
def verify_otp(req: VerifyRequest):
    try:
        db = SessionLocal()
        otp_entry = (
            db.query(PhoneOTP)
            .filter(
                PhoneOTP.phone_number == req.phone_number,
                PhoneOTP.otp_code == req.otp_code,
                PhoneOTP.expires_at > datetime.utcnow(),
            )
            .first()
        )

        if not otp_entry:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")

        api_key_entry = db.query(PhoneAPIKey).filter_by(phone_number=req.phone_number).first()
        if not api_key_entry:
            # Get free plan limits
            free_plan = db.query(SubscriptionPlan).filter_by(name=PlanType.FREE.value).first()
            if not free_plan:
                # Fallback to default free limits
                plan_config = PLAN_CONFIGS[PlanType.FREE]
            else:
                plan_config = {
                    "max_budget": free_plan.max_budget,
                    "max_parallel_requests": free_plan.max_parallel_requests,
                    "tpm_limit": free_plan.tpm_limit,
                    "rpm_limit": free_plan.rpm_limit,
                }

            # Create key from LiteLLM server with free plan limits
            url = f"{LITELLM_URL.rstrip('/')}/key/generate"
            headers = {"Content-Type": "application/json"}
            if ADMIN_KEY:
                headers["Authorization"] = f"Bearer {ADMIN_KEY}"

            payload = {
                "key_alias": req.phone_number,
                "budget_duration": "30d",
                "max_parallel_requests": plan_config["max_parallel_requests"],
                "tpm_limit": plan_config["tpm_limit"],
                "rpm_limit": plan_config["rpm_limit"],
            }
            
            # Only add max_budget if it's not None (for free models access)
            if plan_config["max_budget"] is not None:
                payload["max_budget"] = plan_config["max_budget"]

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to create LiteLLM key")

            api_key_value = r.json().get("key")
            api_key_entry = PhoneAPIKey(phone_number=req.phone_number, api_key=api_key_value)
            db.add(api_key_entry)
            
            # Create free subscription for new user
            if free_plan:
                subscription = UserSubscription(
                    phone_number=req.phone_number,
                    plan_id=free_plan.id,
                    is_active=True
                )
                db.add(subscription)
            
            db.commit()

        return {"api_key": api_key_entry.api_key}
    except Exception as e:
        # Try to initialize database if it failed during startup
        try:
            init_database()
            db = SessionLocal()
            otp_entry = (
                db.query(PhoneOTP)
                .filter(
                    PhoneOTP.phone_number == req.phone_number,
                    PhoneOTP.otp_code == req.otp_code,
                    PhoneOTP.expires_at > datetime.utcnow(),
                )
                .first()
            )

            if not otp_entry:
                raise HTTPException(status_code=400, detail="Invalid or expired OTP")

            api_key_entry = db.query(PhoneAPIKey).filter_by(phone_number=req.phone_number).first()
            if not api_key_entry:
                # Create key from LiteLLM server
                url = f"{LITELLM_URL.rstrip('/')}/key/generate"
                headers = {"Content-Type": "application/json"}
                if ADMIN_KEY:
                    headers["Authorization"] = f"Bearer {ADMIN_KEY}"

                payload = {
                    "key_alias": req.phone_number,
                    "budget_duration": "30d",
                    "max_budget": None,
                    "max_parallel_requests": 3,
                    "tpm_limit": 30000,
                    "rpm_limit": 2,
                }

                r = requests.post(url, json=payload, headers=headers, timeout=30)
                if r.status_code != 200:
                    raise HTTPException(status_code=500, detail="Failed to create LiteLLM key")

                api_key_value = r.json().get("key")
                api_key_entry = PhoneAPIKey(phone_number=req.phone_number, api_key=api_key_value)
                db.add(api_key_entry)
                db.commit()

            return {"api_key": api_key_entry.api_key}
        except Exception as retry_e:
            raise HTTPException(status_code=500, detail=f"Database error: {retry_e}")


@app.get("/spend/logs")
def get_spend_logs(api_key: str | None = None, limit: int = 100, offset: int = 0):
    """
    Return LiteLLM spend logs for a given user api_key.

    - Frontend provides api_key as a query param
    - This endpoint validates api_key exists in our DB (issued by us)
    - Proxies request to LiteLLM using ADMIN_KEY
    """
    try:
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required (query param or Bearer token)")

        # Ensure api_key is one we issued
        db = SessionLocal()
        try:
            existing_key = db.query(PhoneAPIKey).filter_by(api_key=api_key).first()
        finally:
            db.close()

        if not existing_key:
            raise HTTPException(status_code=404, detail="api_key not found")

        url = f"{LITELLM_URL.rstrip('/')}/spend/logs"
        headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
        params = {"api_key": api_key, "limit": limit, "offset": offset}

        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Failed to fetch logs: {r.text}")

        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving spend logs: {e}")


@app.get("/plans")
def get_subscription_plans(db: Session = Depends(get_db)):
    """Get all available subscription plans"""
    plans = db.query(SubscriptionPlan).all()
    return {
        "plans": [
            {
                "id": plan.id,
                "name": plan.name,
                "price_usd": plan.price_usd,
                "max_budget": plan.max_budget,
                "rpm_limit": plan.rpm_limit,
                "tpm_limit": plan.tpm_limit,
                "max_parallel_requests": plan.max_parallel_requests
            }
            for plan in plans
        ]
    }


@app.get("/subscription/{phone_number}")
def get_user_subscription(phone_number: str, db: Session = Depends(get_db)):
    """Get current subscription for user"""
    subscription = db.query(UserSubscription).filter_by(phone_number=phone_number).first()
    
    if not subscription:
        # Create free subscription if none exists
        free_plan = db.query(SubscriptionPlan).filter_by(name=PlanType.FREE.value).first()
        subscription = UserSubscription(
            phone_number=phone_number,
            plan_id=free_plan.id,
            is_active=True
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    
    return {
        "phone_number": subscription.phone_number,
        "plan": {
            "id": subscription.plan.id,
            "name": subscription.plan.name,
            "price_usd": subscription.plan.price_usd,
            "max_budget": subscription.plan.max_budget,
            "rpm_limit": subscription.plan.rpm_limit,
            "tpm_limit": subscription.plan.tpm_limit,
            "max_parallel_requests": subscription.plan.max_parallel_requests
        },
        "is_active": subscription.is_active,
        "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
        "created_at": subscription.created_at.isoformat()
    }


@app.post("/create-checkout-session")
def create_checkout_session(request: CreateCheckoutRequest, req: Request, db: Session = Depends(get_db)):
    """Create Stripe checkout session for subscription upgrade"""
    try:
        if not STRIPE_SECRET_KEY:
            # For development: return mock response with dynamic base URL
            return {
                "checkout_url": f"{BACKEND_ORIGINS}/otp/mock-payment?session_id=cs_mock_123&phone={request.phone_number}&plan={request.plan_type.value}",
                "session_id": "cs_mock_123",
                "message": "Mock response - Set STRIPE_SECRET_KEY for real payments"
            }
            
        if request.plan_type == PlanType.FREE:
            raise HTTPException(status_code=400, detail="Cannot create checkout for free plan")
        
        # Get plan details
        plan = db.query(SubscriptionPlan).filter_by(name=request.plan_type.value).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get or create Stripe customer
        customer_id = get_or_create_stripe_customer(request.phone_number, db)
        
        # Create Stripe checkout session
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'{plan.name} Plan',
                        'description': f'LiteLLM {plan.name} subscription - ${plan.price_usd}/month'
                    },
                    'unit_amount': int(plan.price_usd * 100),  # Convert to cents
                    'recurring': {
                        'interval': 'month'
                    }
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.success_url + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.cancel_url,
            metadata={
                'phone_number': request.phone_number,
                'plan_type': request.plan_type.value
            }
        )
        
        # Save transaction record
        transaction = PaymentTransaction(
            phone_number=request.phone_number,
            stripe_session_id=session.id,
            stripe_payment_intent_id='',  # Will be filled by webhook
            amount_usd=plan.price_usd,
            plan_name=plan.name,
            status='pending'
        )
        db.add(transaction)
        db.commit()
        
        return {"checkout_url": session.url, "session_id": session.id}
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating checkout: {str(e)}")


@app.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhooks"""
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Handle the event
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            await handle_successful_payment(session, db)
            
        elif event['type'] == 'invoice.payment_succeeded':
            invoice = event['data']['object']
            await handle_subscription_renewal(invoice, db)
            
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            await handle_subscription_canceled(subscription, db)
        
        return {"status": "success"}
        
    except Exception as e:
        print(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


async def handle_successful_payment(session, db: Session):
    """Handle successful payment from Stripe checkout"""
    try:
        phone_number = session['metadata']['phone_number']
        plan_type = session['metadata']['plan_type']
        
        # Get plan
        plan = db.query(SubscriptionPlan).filter_by(name=plan_type).first()
        if not plan:
            print(f"Plan not found: {plan_type}")
            return
        
        # Update transaction status
        transaction = db.query(PaymentTransaction).filter_by(
            stripe_session_id=session['id']
        ).first()
        if transaction:
            transaction.status = 'succeeded'
            transaction.stripe_payment_intent_id = session.get('payment_intent', '')
            transaction.updated_at = datetime.utcnow()
        
        # Get or create user subscription
        subscription = db.query(UserSubscription).filter_by(phone_number=phone_number).first()
        if not subscription:
            customer_id = get_or_create_stripe_customer(phone_number, db)
            subscription = UserSubscription(
                phone_number=phone_number,
                stripe_customer_id=customer_id
            )
            db.add(subscription)
        
        # Update subscription
        subscription.plan_id = plan.id
        subscription.stripe_subscription_id = session.get('subscription')
        subscription.is_active = True
        subscription.expires_at = datetime.utcnow() + timedelta(days=30)  # Monthly subscription
        subscription.updated_at = datetime.utcnow()
        
        # Update LiteLLM API key limits
        plan_config = PLAN_CONFIGS[PlanType(plan_type)]
        update_success = update_litellm_api_key(phone_number, plan_config, db)
        
        db.commit()
        
        print(f"✅ Subscription updated for {phone_number} to {plan_type}")
        if not update_success:
            print(f"⚠️ Failed to update LiteLLM limits for {phone_number}")
            
    except Exception as e:
        print(f"Error handling successful payment: {e}")
        db.rollback()


async def handle_subscription_renewal(invoice, db: Session):
    """Handle subscription renewal"""
    try:
        customer_id = invoice['customer']
        
        # Find subscription by customer ID
        subscription = db.query(UserSubscription).filter_by(
            stripe_customer_id=customer_id
        ).first()
        
        if subscription:
            # Extend subscription
            subscription.expires_at = datetime.utcnow() + timedelta(days=30)
            subscription.updated_at = datetime.utcnow()
            subscription.is_active = True
            
            db.commit()
            print(f"✅ Subscription renewed for {subscription.phone_number}")
            
    except Exception as e:
        print(f"Error handling subscription renewal: {e}")


async def handle_subscription_canceled(stripe_subscription, db: Session):
    """Handle subscription cancellation"""
    try:
        subscription_id = stripe_subscription['id']
        
        # Find and deactivate subscription
        subscription = db.query(UserSubscription).filter_by(
            stripe_subscription_id=subscription_id
        ).first()
        
        if subscription:
            # Downgrade to free plan
            free_plan = db.query(SubscriptionPlan).filter_by(name=PlanType.FREE.value).first()
            subscription.plan_id = free_plan.id
            subscription.is_active = True
            subscription.expires_at = None
            subscription.stripe_subscription_id = None
            subscription.updated_at = datetime.utcnow()
            
            # Update LiteLLM API key to free limits
            plan_config = PLAN_CONFIGS[PlanType.FREE]
            update_litellm_api_key(subscription.phone_number, plan_config, db)
            
            db.commit()
            print(f"✅ Subscription canceled and downgraded to free for {subscription.phone_number}")
            
    except Exception as e:
        print(f"Error handling subscription cancellation: {e}")


@app.get("/debug/config")
def debug_config():
    """Debug endpoint to check configuration"""
    return {
        "LITELLM_URL": LITELLM_URL,
        "ADMIN_KEY_present": "Yes" if ADMIN_KEY else "No",
        "ADMIN_KEY_length": len(ADMIN_KEY) if ADMIN_KEY else 0,
        "STRIPE_SECRET_KEY_present": "Yes" if STRIPE_SECRET_KEY else "No",
        "DATABASE_URL": DATABASE_URL.replace(POSTGRES_PASSWORD, "***") if POSTGRES_PASSWORD else DATABASE_URL,
        "PLAN_CONFIGS": PLAN_CONFIGS
    }


@app.get("/health")
def health_check():
    """Health check endpoint for Docker"""
    try:
        # Test database connection
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        
        # Test LiteLLM connection
        litellm_status = "unknown"
        try:
            response = requests.get(f"{LITELLM_URL}/health", timeout=10)
            litellm_status = "connected" if response.status_code == 200 else f"error_{response.status_code}"
        except Exception as e:
            litellm_status = f"failed: {str(e)}"
        
        return {
            "status": "healthy", 
            "database": "connected",
            "litellm": litellm_status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/mock-payment")
def mock_payment_page(request: Request, session_id: str, phone: str, plan: str, success_url: str = None, cancel_url: str = None):
    """Mock payment page for development"""
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mock Payment - {plan.title()} Plan</title>
        <style>
            body {{ font-family: Arial; max-width: 400px; margin: 50px auto; padding: 20px; }}
            .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 20px; }}
            button {{ padding: 10px 20px; margin: 10px; border-radius: 5px; cursor: pointer; }}
            .success {{ background: #28a745; color: white; border: none; }}
            .cancel {{ background: #dc3545; color: white; border: none; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>🚀 Mock Payment</h2>
            <p><strong>Phone:</strong> {phone}</p>
            <p><strong>Plan:</strong> {plan.title()}</p>
            <p><strong>Session ID:</strong> {session_id}</p>
            <hr>
            <p>This is a mock payment page for development.</p>
            <button class="success" onclick="simulateSuccess()">✅ Simulate Success</button>
            <button class="cancel" onclick="simulateCancel()">❌ Simulate Cancel</button>
        </div>
        
        <script>
            function simulateSuccess() {{
                // Simulate successful payment webhook
                fetch('{BACKEND_ORIGINS}/otp/webhook-mock', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        session_id: '{session_id}',
                        phone_number: '{phone}',
                        plan_type: '{plan}',
                        status: 'success'
                    }})
                }})
                .then(response => {{
                    if (response.ok) {{
                        return response.json();
                    }} else {{
                        throw new Error('Network response was not ok');
                    }}
                }})
                .then(data => {{
                    console.log('Success:', data);
                    alert('Payment simulated successfully! Redirecting...');
                    window.location.href = 'https://demoaiconnex.space/payment-success?session_id={session_id}';
                }})
                .catch(error => {{
                    console.error('Error:', error);
                    alert('Error simulating payment: ' + error.message);
                }});
            }}
            
            function simulateCancel() {{
                alert('Payment cancelled');
                window.location.href = 'https://demoaiconnex.space/payment-cancel';
            }}
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@app.post("/webhook-mock")
async def webhook_mock(request: Request, db: Session = Depends(get_db)):
    """Mock webhook for development"""
    try:
        # Parse JSON body from request - await the coroutine
        body = await request.json()
        phone_number = body.get('phone_number')
        plan_type = body.get('plan_type')
        
        if not phone_number or not plan_type:
            return {"error": "Missing phone_number or plan_type"}
        
        print(f"🔄 [DEBUG] Processing mock webhook for {phone_number} -> {plan_type}")
        
        # Get plan
        plan = db.query(SubscriptionPlan).filter_by(name=plan_type).first()
        if not plan:
            print(f"❌ [ERROR] Plan not found: {plan_type}")
            return {"error": f"Plan not found: {plan_type}"}
        
        print(f"✅ [DEBUG] Found plan: {plan.name} (ID: {plan.id})")
        
        # Get or create user subscription
        subscription = db.query(UserSubscription).filter_by(phone_number=phone_number).first()
        if not subscription:
            print(f"🆕 [DEBUG] Creating new subscription for {phone_number}")
            subscription = UserSubscription(phone_number=phone_number)
            db.add(subscription)
        else:
            print(f"📝 [DEBUG] Updating existing subscription for {phone_number}")
        
        # Update subscription
        subscription.plan_id = plan.id
        subscription.is_active = True
        subscription.expires_at = datetime.utcnow() + timedelta(days=30)
        subscription.updated_at = datetime.utcnow()
        
        # Update LiteLLM API key limits
        plan_config = PLAN_CONFIGS[PlanType(plan_type)]
        print(f"🔄 [DEBUG] Updating LiteLLM limits for {phone_number} to {plan_type}")
        print(f"📋 [DEBUG] Plan config: {plan_config}")
        
        update_success = update_litellm_api_key(phone_number, plan_config, db)
        print(f"✅ [DEBUG] LiteLLM update result: {update_success}")
        
        db.commit()
        print(f"💾 [DEBUG] Database committed successfully")
        
        result = {
            "status": "success", 
            "message": f"Mock upgrade to {plan_type} successful",
            "phone_number": phone_number,
            "plan_type": plan_type,
            "plan_id": plan.id
        }
        
        if update_success:
            result["litellm_update"] = "✅ LiteLLM limits updated successfully"
        else:
            result["litellm_update"] = "⚠️ Failed to update LiteLLM limits"
            
        print(f"🎉 [SUCCESS] Mock webhook completed: {result}")
        return result
        
    except Exception as e:
        print(f"💥 [ERROR] Mock webhook failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "type": type(e).__name__}


@app.get("/test-litellm-update/{phone_number}")
def test_litellm_update(phone_number: str, db: Session = Depends(get_db)):
    """Test endpoint to manually trigger LiteLLM key update"""
    try:
        # Get user's current subscription
        subscription = db.query(UserSubscription).filter_by(phone_number=phone_number).first()
        if not subscription:
            return {"error": "No subscription found for this phone number"}
        
        # Get plan config
        plan_config = PLAN_CONFIGS[PlanType(subscription.plan.name)]
        
        # Test the update
        update_success = update_litellm_api_key(phone_number, plan_config, db)
        
        return {
            "phone_number": phone_number,
            "current_plan": subscription.plan.name,
            "plan_config": plan_config,
            "update_success": update_success,
            "message": "Test completed"
        }
        
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}
