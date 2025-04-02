# QuickBooks OAuth Integration Setup Guide

## Common Issues with QuickBooks OAuth

### Issue 1: Invalid Redirect URI

The error **"The redirect_uri query parameter value is invalid"** happens because there's a mismatch between:
1. The redirect URI that's registered in your Intuit Developer Dashboard
2. The redirect URI that our application is sending during the OAuth flow

### Issue 2: Authorization Code Has Expired or Already Been Used

The error **"The authorization code has expired or already been used"** occurs when:
1. You attempt to use the same authorization code more than once
2. You wait more than 10 minutes to exchange the code for tokens

## How to Fix These Issues

### For Invalid Redirect URI:

#### Option 1: Update Your Intuit Developer Dashboard (Recommended)

1. Log into the [Intuit Developer Dashboard](https://developer.intuit.com/app/developer/dashboard)
2. Select your application
3. Go to the **Keys & OAuth** tab
4. In the **Redirect URIs** section, add or modify the URI to exactly match:
   ```
   https://b1518f9f-8980-4a58-b73b-3dd813ffa3f5-00-ee9n49p8ejxm.picard.replit.dev/callback
   ```
   (This is the URI our application is currently using)
5. Save your changes
6. Try the authorization process again

#### Option 2: Update Our Application Code

If you can't modify the Intuit Developer Dashboard (or prefer not to), you can modify our code to match your registered redirect URI:

1. Open the `app.py` file
2. Locate the `get_quickbooks_auth_url` function
3. Find the section that sets the `default_redirect_uri` variable
4. Uncomment the appropriate option or modify it to match what's registered in your Intuit Developer Dashboard

### For Expired/Used Authorization Code:

1. Start the authorization process fresh:
   - Click "Continue to Application" to clear any current parameters
   - Go back to the QuickBooks settings page
   - Click "Connect to QuickBooks" again
   - Complete the authorization quickly (within 10 minutes)

2. Don't refresh the page during authorization:
   - Once you're redirected back to the application after authorizing, let the process complete
   - Avoid refreshing the page or navigating away

3. Clear browser cache if issues persist:
   - Browser cache can sometimes cause problems with OAuth flows
   - Try opening in an incognito/private window

## QuickBooks OAuth Flow Explained

1. User clicks "Connect to QuickBooks"
2. User is redirected to Intuit login page
3. After successful authorization, Intuit redirects back to our app with an authorization code
4. Our app exchanges this code for access and refresh tokens (can only be done once)
5. Tokens are stored in the database for future API calls

## Important Notes

1. The redirect URI must match **EXACTLY** what's in your Intuit Developer Dashboard, including protocol, domain name, path, and any query parameters.

2. If your Replit URL changes (which can happen when a repl restarts), you'll need to update your Intuit Developer Dashboard again.

3. Authorization codes expire after 10 minutes and can only be used once.

4. In a production environment, use a stable domain name registered specifically for your application.

## Need More Help?

Intuit provides detailed documentation about OAuth implementation at:
https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization