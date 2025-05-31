#! /usr/bin/env python3.6

import os
from flask import Flask, jsonify, redirect, request, abort
import stripe

stripe.api_key = 'sk_test_51RS0iTHBc2BQhQpd7U1M8SX3mNDtveLR0ItmVWPR5fzqjNA2UwiEzclw27mxW4d8ynjBvl6cDhIHZ9kVeNZYqErw00oKalX4d7'

app = Flask(__name__, static_url_path='', static_folder='public')

YOUR_DOMAIN = 'http://localhost:4242'
YOUR_PRODUCT_ID = 'prod_SPnt2yMB3QVrLX'  
WEBHOOK_SECRET = 'whsec_XXXXXXXXXXXXXXXX'  # Replace with your Stripe webhook secret

MAX_KIDS = 5
MAX_BIWEEKLY_PAYMENTS = 3

endpoint_secret = 'whsec_...'  # Replace with your actual webhook secret

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('stripe-signature')
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        # Invalid payload
        print('⚠️ Invalid payload')
        return jsonify(success=False), 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        print('⚠️ Invalid signature')
        return jsonify(success=False), 400

    # Handle the event types you care about
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        print(f"✅ Checkout session completed: {session['id']}")
        # TODO: Fulfill the order or update DB

    elif event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        print(f"✅ Invoice paid: {invoice['id']}")
        # TODO: Update your records if on a subscription

    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        print(f"❌ Payment failed for invoice {invoice['id']}")

    else:
        print(f"Unhandled event type: {event['type']}")

    return jsonify(success=True), 200

def calculate_total_price(number_of_kids):
    # Discounted price formula: 425 + (kids -1) * 400
    if number_of_kids < 1:
        raise ValueError("Must register at least one kid.")
    if number_of_kids > MAX_KIDS:
        raise ValueError(f"Cannot register more than {MAX_KIDS} kids.")
    return 425 + (number_of_kids - 1) * 400


def create_biweekly_price(amount_cents):
    """
    Create a dynamic recurring price in Stripe for biweekly payments.
    amount_cents = total amount for one payment (total_price / 3)
    """
    price = stripe.Price.create(
        unit_amount=amount_cents,
        currency='usd',
        recurring={'interval': 'week', 'interval_count': 2},
        product=YOUR_PRODUCT_ID,
    )
    return price.id


@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        data = request.json
        number_of_kids = int(data.get('number_of_kids', 1))
        payment_type = data.get('payment_type', 'full').lower()

        total_price = calculate_total_price(number_of_kids)
        total_cents = int(total_price * 100)

        if payment_type == 'full':
            # Create one-time payment Price
            # For simplicity, we assume a Price created in Stripe dashboard for $1
            # and use quantity to adjust total, but better to create dynamic Price here
            # Let's create a one-time dynamic Price on the fly:

            price = stripe.Price.create(
                unit_amount=total_cents,
                currency='usd',
                product=YOUR_PRODUCT_ID,
            )
            price_id = price.id

            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='payment',
                success_url=YOUR_DOMAIN + '/return.html?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=YOUR_DOMAIN + '/checkout.html',
            )

        elif payment_type == 'biweekly':
            # Divide total by 3 payments
            per_payment_cents = total_cents // MAX_BIWEEKLY_PAYMENTS

            # Create dynamic recurring price for biweekly payments
            price_id = create_biweekly_price(per_payment_cents)

            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': number_of_kids,
                }],
                mode='subscription',
                subscription_data={
                    'metadata': {
                        'paid_cycles': '0',  # Custom metadata to track payments
                        'max_cycles': str(MAX_BIWEEKLY_PAYMENTS),
                    }
                },
                success_url=YOUR_DOMAIN + '/return.html?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=YOUR_DOMAIN + '/checkout.html',
            )

        else:
            return jsonify(error='Invalid payment_type, must be "full" or "biweekly"'), 400

        return jsonify(clientSecret=session.client_secret)

    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route('/session-status', methods=['GET'])
def session_status():
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify(error='session_id required'), 400
    session = stripe.checkout.Session.retrieve(session_id)
    return jsonify(status=session.status, customer_email=session.customer_details.email)


@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, WEBHOOK_SECRET
        )
    except ValueError:
        # Invalid payload
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        return 'Invalid signature', 400

    if event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        subscription_id = invoice['subscription']

        # Retrieve the subscription to check/update metadata
        subscription = stripe.Subscription.retrieve(subscription_id)

        paid_cycles = int(subscription.metadata.get('paid_cycles', '0')) + 1
        max_cycles = int(subscription.metadata.get('max_cycles', str(MAX_BIWEEKLY_PAYMENTS)))

        # Update paid cycles count
        stripe.Subscription.modify(
            subscription_id,
            metadata={'paid_cycles': str(paid_cycles), 'max_cycles': str(max_cycles)}
        )

        if paid_cycles >= max_cycles:
            # Cancel subscription at period end to stop future payments
            stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )

    return '', 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 4242)))