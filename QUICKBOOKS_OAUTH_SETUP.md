# QuickBooks OAuth Integration Setup Guide

## Quick Start: Essential Steps

1. **Set Replit Secrets** (Tools > Secrets):
   - `QB_CLIENT_ID`: Your Intuit application Client ID
   - `QB_CLIENT_SECRET`: Your Intuit application Client Secret 
   - `QB_REDIRECT_URI`: Must exactly match what's in Intuit Developer Dashboard

2. **Configure Intuit Developer Dashboard**:
   - Add your callback URL: `https://your-replit-domain.replit.dev/callback`
   - **URI Must Match Exactly** – No extra slashes, parameters, or differences

3. **Connect in Application**:
   - Go to Admin Settings > QuickBooks Integration
   - Click "Connect to QuickBooks"
   - Authorize when redirected to Intuit
   - You'll be redirected back to your application

## Most Common Error: "Invalid authorization code" 🚨

The error `{"error":"invalid_grant","error_description":"Invalid authorization code"}` typically happens for one of these reasons:

### 1. Redirect URI Mismatch (Most Common)

The redirect URI in your Replit Secrets **MUST** exactly match what's in your Intuit Developer Dashboard, down to the last character:

✅ **Correct Example**:  
Both in Replit Secrets and Intuit Dashboard: `https://myapp.replit.dev/callback`

❌ **Incorrect Examples**:  
- Different protocol: `http://myapp.replit.dev/callback` vs `https://myapp.replit.dev/callback`
- Extra slash: `https://myapp.replit.dev/callback/` vs `https://myapp.replit.dev/callback`
- Different path: `https://myapp.replit.dev/oauth/callback` vs `https://myapp.replit.dev/callback`

### 2. Code Reuse

**Authorization codes can only be used once.** If you:
- Refresh the page during authentication
- Try to use the same authorization link twice
- Have two browser tabs open with your application

You'll get this error because the code was already used.

### 3. Code Expiration

Authorization codes expire after 10 minutes. Complete the process quickly.

## Step-by-Step Setup with Screenshots

### Step 1: Create or Configure Intuit Developer App

1. Log into [Intuit Developer Dashboard](https://developer.intuit.com/app/developer/dashboard)
2. Create a new app or select existing app
3. Go to the "Keys & OAuth" section

### Step 2: Configure Redirect URI in Intuit Developer Dashboard

![Configure Redirect URI](https://i.imgur.com/5F1kqo2.png)

1. In the **Redirect URIs** section, add your specific Replit URL:
   ```
   https://your-replit-domain.replit.dev/callback
   ```
2. Make sure the URI includes `/callback` at the end
3. Save your changes

### Step 3: Get OAuth Credentials

From the same "Keys & OAuth" page, find:
1. **Client ID** 
2. **Client Secret**

### Step 4: Set Replit Secrets

1. In your Replit project, go to **Tools > Secrets**
2. Add these three secrets:
   - `QB_CLIENT_ID`: Your app's client ID
   - `QB_CLIENT_SECRET`: Your app's client secret
   - `QB_REDIRECT_URI`: EXACT redirect URI (e.g., `https://your-replit-domain.replit.dev/callback`)

### Step 5: Connect in the Application

1. Go to the Admin Settings tab 
2. Open QuickBooks Integration Settings
3. Click "Connect to QuickBooks"
4. Follow the Intuit authorization flow
5. You'll be automatically redirected back to your application

## Complete Troubleshooting Guide

### A. "Invalid authorization code" Error Fix

If you see this error:

1. **Verify URI Match**: Double-check that the `QB_REDIRECT_URI` in Replit Secrets **exactly** matches what's in your Intuit Developer Dashboard.

2. **Reset and Restart**:
   - Go to Admin Settings > QuickBooks Integration
   - Use the "Reset QuickBooks Connection" button
   - Close all browser tabs with your application
   - Start the process again from scratch

3. **Incognito Window**: Use an incognito/private browser window to eliminate caching issues.

4. **Fresh Start**: Delete and recreate the redirect URI in your Intuit Developer Dashboard, then update the Replit Secret to match exactly.

### B. "Invalid client" Error Fix

This error typically indicates credential issues:

1. **Check Credentials**: Verify your Client ID and Client Secret are correct. They are case-sensitive.

2. **Regenerate Credentials**: In the Intuit Developer Dashboard, you may need to regenerate your credentials if you suspect they're compromised.

3. **Environment Mismatch**: Make sure you're accessing the correct environment (sandbox/production).

### C. "Token expired" Error Fix

1. **Automatic Refresh**: The application normally refreshes tokens automatically.

2. **Manual Reset**: If tokens don't refresh properly:
   - Reset your QuickBooks connection
   - Reconnect from scratch

## OAuth Flow Explained

Our authentication flow is simplified to reduce errors:

1. Application retrieves credentials from Replit Secrets
2. App creates a secure state parameter to prevent CSRF attacks
3. User is redirected to QuickBooks for authorization
4. After authorization, QuickBooks redirects back with a code
5. Application exchanges code for access/refresh tokens
6. Tokens are securely stored in database and automatically refreshed

## Advanced Troubleshooting

### Database Connection Issues

If tokens aren't being stored properly:

1. Check database connection status in the application
2. Verify database tables are created correctly
3. Check for any database errors in the logs

### URL Parameter Issues

The callback includes important parameters:
- `code`: The authorization code
- `realmId`: Your QuickBooks company ID
- `state`: Security parameter to prevent CSRF attacks

If any are missing, the OAuth process will fail.

### Tools for Diagnosis

1. **Application Logs**: Check for detailed error messages
2. **Network Inspector**: Use browser developer tools to inspect the OAuth requests
3. **Error Messages**: Look for specific error codes in QuickBooks API responses

## Need More Help?

1. **QuickBooks Developer Documentation**:
   - [OAuth 2.0 Guide](https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization/oauth-2.0)
   - [Authentication Errors](https://developer.intuit.com/app/developer/qbo/docs/develop/troubleshooting/oauth)

2. **Reset & Restart**: When in doubt, reset the entire authentication process:
   - Reset QuickBooks connection in Admin Settings
   - Update your Replit Secrets
   - Verify redirect URI exact match
   - Start fresh with a new authorization attempt

Remember: The exact match of redirect URI is the most common issue. Double-check this first!