# stripe_test.py
from dotenv import load_dotenv
load_dotenv()
import os, stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY") or ""
print("stripe.api_key present?", bool(stripe.api_key), "prefix:", (stripe.api_key or "")[:12])

# Use a safe test minimum (₹50 -> 5000 paise)
MIN_PAISA = 5000

try:
    # create a tiny PaymentIntent as a smoke-test using ₹50
    pi = stripe.PaymentIntent.create(amount=MIN_PAISA, currency="inr", payment_method_types=["card"], metadata={"test":"1"})
    print("PaymentIntent created id:", pi.id)
except Exception as e:
    print("Stripe create failed:", e)
