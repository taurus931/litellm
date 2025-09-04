from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import stripe
import os
import requests
from typing import Optional

from main import (
    SessionLocal, SubscriptionPlan, UserSubscription, PaymentTransaction, 
    PhoneAPIKey, PlanType, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
    LITELLM_URL, ADMIN_KEY
)

# Stripe config
stripe.api_key = STRIPE_SECRET_KEY

# Plan configurations
PLAN_CONFIGS = {
    PlanType.FREE: {
        "name": "Free",
        "price_usd": 0.0,
        "max_budget": 0.0,
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

app = FastAPI(title="Payment Service", version="1.0.0")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class CreateCheckoutRequest(BaseModel):
    phone_number: str
    plan_type: PlanType
    success_url: str
    cancel_url: str

class WebhookRequest(BaseModel):
    pass

def init_subscription_plans(db: Session):
    """Initialize default subscription plans if they don't exist"""
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
        api_key_entry = db.query(PhoneAPIKey).filter_by(phone_number=phone_number).first()
        if not api_key_entry:
            return False

        # Update key via LiteLLM API
        url = f"{LITELLM_URL.rstrip('/')}/key/update"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ADMIN_KEY}"
        }
        
        payload = {
            "key": api_key_entry.api_key,
            "max_budget": plan_config["max_budget"],
            "budget_duration": "30d",
            "max_parallel_requests": plan_config["max_parallel_requests"],
            "tpm_limit": plan_config["tpm_limit"],
            "rpm_limit": plan_config["rpm_limit"],
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        return response.status_code == 200
        
    except Exception as e:
        print(f"Error updating LiteLLM key: {e}")
        return False

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        init_subscription_plans(db)
        print("✅ Payment service initialized")
    finally:
        db.close()

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
def create_checkout_session(request: CreateCheckoutRequest, db: Session = Depends(get_db)):
    """Create Stripe checkout session for subscription upgrade"""
    try:
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

@app.get("/health")
def health_check():
    """Health check for payment service"""
    return {"status": "healthy", "service": "payment"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)