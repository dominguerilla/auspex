# Context
I want to minimize the amount of vertical scrolling users have to do, both for the 'desktop' and 'mobile' resolutions. 
## General idea
1. having a 'welcome page' type thing with the hero and the taglines, with an 'ask your question' button that opens a text + slider + submit button. (Perhaps the circle could still be faintly visible in the background?)
2. Submitting fades away the 'welcome page' and the circle focuses--it's just the header, circle, and footer while the circle does its animation. (Maybe each 'spirit sigil' or a 'detailed view button' is clickable that shows the progress bits that "THE WORKING" section currently shows?)
3. When the report is complete, the center of the circle glows and can be clicked, revealing the report.

# Generated Prototype of Context (by Claude Design)
A single-viewport flow prototype at prototype.html.

## How it works
Welcome — hero centered, circle faintly visible behind the title, single "Pose the Question" CTA.
Composing — the welcome shifts up, the blurb + CTA fade away, and a textarea + slider + submit panel slides up from the bottom. (Esc / Cancel returns.)
Working — the welcome fades out, the Circle scales up to the center and animates through the six spirits. The question shrinks to a small epigraph at the top. A 6-segment progress bar + active spirit name sits below. Each sigil is a clickable hit zone — clicking opens that spirit's testimony in a centered manuscript-card with the Circle dimmed behind it.
Complete — the center of the Circle glows with a slow pulse. "Receive the Testimony · Open the Scroll" appears below. Clicking the heart (or the button) expands the report scroll from the middle.
Other notes

The Circle is one persistent element across all phases — scaled and faded via phase-keyed CSS vars rather than mounted/unmounted, so the transitions feel like one continuous spatial movement instead of three disconnected screens.
No outer scrolling at desktop or phone (container queries collapse the layout below 720px). The report overlay scrolls internally.