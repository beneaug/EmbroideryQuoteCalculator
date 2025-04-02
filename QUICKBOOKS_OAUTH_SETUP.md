# QuickBooks OAuth Integration Setup Guide

## The Issue: Invalid Redirect URI

The error you're seeing: **"The redirect_uri query parameter value is invalid"** is happening because there's a mismatch between:
1. The redirect URI that's registered in your Intuit Developer Dashboard
2. The redirect URI that our application is sending during the OAuth flow

## How to Fix It

You have two options:

### Option 1: Update Your Intuit Developer Dashboard (Recommended)

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

### Option 2: Update Our Application Code

If you can't modify the Intuit Developer Dashboard (or prefer not to), you can modify our code to match your registered redirect URI:

1. Open the `app.py` file
2. Locate the `get_quickbooks_auth_url` function
3. Find the section that sets the `default_redirect_uri` variable
4. Uncomment the appropriate option or modify it to match what's registered in your Intuit Developer Dashboard:

```python
# Option 1: If you registered with /callback path (most common)
default_redirect_uri = f"https://{replit_domain}/callback"

# Option 2: If you registered the root domain without path
# Uncomment this line if Option 1 doesn't work
# default_redirect_uri = f"https://{replit_domain}"

# Option 3: If you registered with a different path
# default_redirect_uri = f"https://{replit_domain}/your-custom-path"
```

## Important Notes

1. The redirect URI must match **EXACTLY** what's in your Intuit Developer Dashboard, including:
   - Protocol (http vs https)
   - Domain name (including subdomains)
   - Path (including slashes)
   - Query parameters (if any)

2. If your Replit URL changes (which can happen when a repl restarts), you'll need to update your Intuit Developer Dashboard again.

3. In a production environment, you should use a stable domain name registered specifically for your application.

## Need More Help?

If you continue to have issues, Intuit provides documentation about OAuth implementation at:
https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization