#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

npm install

# Build the @gdexsdk/gdex-skill SDK from source (it ships as TypeScript and
# requires a compile step to produce the dist/index.js CJS entry point).
SDK_DIR="$SCRIPT_DIR/node_modules/@gdexsdk/gdex-skill"
if [ -d "$SDK_DIR" ] && [ ! -f "$SDK_DIR/dist/index.js" ]; then
  echo "Building @gdexsdk/gdex-skill..."
  cd "$SDK_DIR"
  npm install --include=dev --no-fund --no-audit 2>/dev/null || true

  # Write a minimal tsconfig if one doesn't exist.
  if [ ! -f tsconfig.json ]; then
    cat > tsconfig.json << 'TSEOF'
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["ES2020"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": false,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "resolveJsonModule": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
TSEOF
  fi

  npx tsc 2>/dev/null || \
    npx --yes tsc 2>/dev/null || \
    echo "Warning: SDK build failed; helpers may not work until node_modules are set up manually."

  cd "$SCRIPT_DIR"
fi

echo "GDEX trading helpers installed successfully."
