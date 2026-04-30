# Environment Setup Guide

## Setting OPENAI_API_KEY

The OpenAI API key is required for AI-powered message generation (when using templates with `template_type: "ai_prompt"`).

### Option 1: Using .env file (Recommended)

1. Create a `.env` file in the project root:

```bash
cd /root/openoutreach
touch .env
```

2. Add your OpenAI API key:

```bash
echo "OPENAI_API_KEY=sk-your-actual-api-key-here" >> .env
```

3. The application will automatically load it (uses `python-dotenv`)

### Option 2: Export as environment variable

```bash
export OPENAI_API_KEY=sk-your-actual-api-key-here
```

### Option 3: Set when running the server

```bash
OPENAI_API_KEY=sk-your-actual-api-key-here python -m uvicorn api.main:app --reload
```

### Getting Your OpenAI API Key

1. Go to https://platform.openai.com/api-keys
2. Sign in or create an account
3. Click "Create new secret key"
4. Copy the key (starts with `sk-`)
5. Add it to your `.env` file or export it

### Optional: Set AI Model

You can also specify which OpenAI model to use:

```bash
# In .env file
AI_MODEL=gpt-4o-mini  # Default, cheaper
# or
AI_MODEL=gpt-4o       # More powerful, more expensive
```

### Verify It's Working

After setting the key, restart your server and check the logs. You should NOT see:

```
ERROR - OPENAI_API_KEY is not set in the environment or config.
```

## Note

- The `.env` file is already in `.gitignore`, so your key won't be committed
- Never share your API key publicly
- The key is only needed if you're using AI-powered message templates



