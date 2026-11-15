# SmartCut AI — Web Beta

A mobile-first browser prototype for the SmartCut AI concept.

## Current prototype
- Select a reference video and multiple source clips.
- Preview local files in the browser.
- Read duration and frame dimensions.
- Sample frame brightness locally in the browser.
- Generate and download a preliminary edit-plan JSON with a proposed clip order and target duration.

## Important limitations
This is an early interface and workflow prototype, not the final AI editing engine. It does not yet understand semantic scene content, identify exact transitions/effects from the reference, render a finished edited video, or perform professional color grading. All media processing in this version happens locally in the browser; selected video files are not uploaded.

## Publish
GitHub Actions deploys the contents of this folder to GitHub Pages when changes are pushed to the `smartcut-rebuild` branch. In repository Settings → Pages, choose **GitHub Actions** as the build and deployment source if Pages is not already configured.