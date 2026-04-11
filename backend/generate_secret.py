import pyotp
import sys

def main():
    print("Generating a new Base32 Secret for Microsoft Authenticator (or any TOTP app)...")
    secret = pyotp.random_base32()
    print(f"\nYour new TOTP Secret is: {secret}")
    print("\nIMPORTANT: Copy this secret and add it to your .env file as APP_MFA_SECRET")
    
    # Generate a provisioning URI for convenience, user can use an online QR generator or just type the secret.
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name="MkDocs_Admin", issuer_name="MkDocs-Chatbox")
    print("\nIf you want to create a QR code, you can use the following URI:")
    print(uri)
    print("\nTo manually add in Microsoft Authenticator:")
    print("1. Click '+' to add account")
    print("2. Choose 'Other'")
    print("3. Enter Code Manually")
    print("4. Account Name: MkDocs_Admin")
    print(f"5. Secret Key: {secret}")

if __name__ == "__main__":
    main()
