# Instructions for Creating App Icons

The Teams app requires two icon files:

## 1. color.png (192x192 px)
- Full color icon displayed in Teams app catalog
- Recommended: Blue/purple gradient with Aurora logo
- Current placeholder: Letter "A" with orbital rings

## 2. outline.png (32x32 px)
- Transparent background with black/white outline
- Used in Teams UI when app is active
- Current placeholder: Simple letter "A"

## How to Create Real Icons

### Option 1: Convert SVG to PNG
```bash
# Install ImageMagick or use online converter
brew install imagemagick  # macOS
sudo apt-get install imagemagick  # Linux

# Convert SVG files to PNG
convert -background none color.svg -resize 192x192 color.png
convert -background none outline.svg -resize 32x32 outline.png
```

### Option 2: Use Design Tool
1. Open Figma, Canva, or Adobe Illustrator
2. Create 192x192 px artboard for color icon
3. Add Aurora logo/branding with #4A90E2 background
4. Export as PNG

5. Create 32x32 px artboard for outline
6. Add simple outline version (black on transparent)
7. Export as PNG

### Option 3: Use Online Tool
- [Favicon Generator](https://realfavicongenerator.net/)
- [App Icon Generator](https://appicon.co/)
- Upload your logo and generate both sizes

## Design Guidelines

### Color Icon (192x192)
- Use brand colors (#4A90E2 recommended)
- Include recognizable Aurora branding
- Ensure good contrast
- Round corners (16px radius) look modern
- Add subtle shadow or glow for depth

### Outline Icon (32x32)
- Keep it simple and recognizable
- Use solid black or white (no gradients)
- Transparent background required
- Must be visible on light and dark backgrounds
- Usually a simplified version of the color icon

## Quick Test
After creating icons, test them:
1. Open `manifest.json` in VS Code
2. Icons should preview correctly
3. Package and upload to Teams to verify appearance

## Current Placeholders
The current SVG placeholders are functional but basic.
Replace them with proper branded icons before production deployment.
