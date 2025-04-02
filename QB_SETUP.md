# QuickBooks Integration: Simple Setup Guide

This guide explains how to set up and test the QuickBooks integration for our application.

## 1. Prerequisites

You need:
- Intuit Developer account
- Application created in Intuit Developer Dashboard
- QuickBooks sandbox company for testing

## 2. Setup Steps

### Get Your Credentials

1. Go to [Intuit Developer Dashboard](https://developer.intuit.com/app/developer/dashboard)
2. Select your application
3. Go to the **Keys & OAuth** tab
4. Note your **Client ID** and **Client Secret**
5. Add the following **Redirect URI** to your application:
   ```
   https://your-replit-domain.replit.dev/callback
   ```
   (Replace "your-replit-domain" with your actual Replit domain)

### Configure Your Application

1. In Replit, go to **Tools > Secrets**
2. Add the following secrets:
   - `QB_CLIENT_ID`: Your Intuit application Client ID
   - `QB_CLIENT_SECRET`: Your Intuit application Client Secret
   - `QB_REDIRECT_URI`: The exact redirect URI you configured in Intuit Developer Dashboard

### Test the Integration

After setting up your credentials:

1. Run `python quickbooks_test.py` to verify your credentials
2. Run `streamlit run quickbooks_app.py` to test the full OAuth flow
3. Click "Connect to QuickBooks" to start the authorization process
4. Log in to your QuickBooks sandbox company
5. Authorize the connection
6. You should be redirected back to your application

## 3. Understanding the Authentication Flow

The QuickBooks integration follows the standard OAuth 2.0 flow:

1. User clicks "Connect to QuickBooks"
2. Application generates an authorization URL
3. User is redirected to QuickBooks to log in and authorize
4. QuickBooks redirects back to our application with an authorization code
5. Application exchanges the code for access and refresh tokens
6. Tokens are stored securely for future API calls

## 4. Common Issues and Solutions

### "Invalid authorization code" Error

This happens when:
1. The code has already been used (they are one-time use only)
2. The code has expired (they expire after 10 minutes)
3. The redirect URI doesn't match exactly

**Solution**: Reset your connection and try again with a fresh authorization.

### Redirect URI Mismatch

The redirect URI in your Replit Secrets must match EXACTLY what's configured in your Intuit Developer Dashboard.

**Examples of mismatches**:
- `https://myapp.replit.dev/callback` vs `https://myapp.replit.dev/callback/` (trailing slash)
- `http://myapp.replit.dev/callback` vs `https://myapp.replit.dev/callback` (http vs https)

### Token Expired

Access tokens expire after a few hours. Our client automatically refreshes them when needed.

If you encounter persistent issues with expired tokens, reset your connection and reconnect.

## 5. Using the QuickBooks API

Once connected, you can use the QuickBooks API to access your company data:

```python
# Get QuickBooks client
qb_client = QuickBooksClient(db_connection)
client, error = qb_client.get_api_client()

if client:
    # Access QuickBooks data
    from quickbooks.objects.customer import Customer
    customers = Customer.all(qb=client)
    
    # Create a new customer
    new_customer = Customer()
    new_customer.DisplayName = "New Customer"
    new_customer.save(qb=client)
```

## 6. Security Considerations

- Never hardcode your credentials in your application
- Always use environment variables or secure storage for sensitive information
- Protect your Client Secret as you would a password

## 7. Testing Tools

We provide two tools to help test your integration:

1. `quickbooks_test.py` - Command-line test script for checking credentials
2. `quickbooks_app.py` - Streamlit app for testing the full OAuth flow