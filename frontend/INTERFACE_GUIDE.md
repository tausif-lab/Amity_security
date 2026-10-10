# Visual Interface Guide

A visual walkthrough of the Network Security Compliance frontend.

## Layout Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     HERO SECTION                            │
│  ┌──────────────────────┬──────────────────────────────┐   │
│  │                      │                              │   │
│  │  Network Security    │   ┌──────────────────────┐  │   │
│  │  Compliance          │   │ Upload Configuration │  │   │
│  │  Automation          │   │                      │  │   │
│  │                      │   │ [Vendor Dropdown]    │  │   │
│  │  Analyze network...  │   │ [File Upload]        │  │   │
│  │                      │   │ [Analyze Button]     │  │   │
│  │                      │   └──────────────────────┘  │   │
│  └──────────────────────┴──────────────────────────────┘   │
│                                                             │
│                     RESULTS SECTION                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Compliance Report              [Download PDF]      │   │
│  │  ┌───────────┬───────────┬─────────┐               │   │
│  │  │ ID: xxx   │ Vendor    │ Status  │               │   │
│  │  └───────────┴───────────┴─────────┘               │   │
│  │  ┌────────┬────────┬────────┬──────────┐           │   │
│  │  │ Total  │ Passed │ Failed │ Critical │           │   │
│  │  │   8    │   4    │   3    │    2     │           │   │
│  │  └────────┴────────┴────────┴──────────┘           │   │
│  │                                                     │   │
│  │  Baseline Configuration                            │   │
│  │  ┌──────────────────┬──────────────────┐           │   │
│  │  │ Hostname: xxx    │ SSH Version: 2   │           │   │
│  │  │ Vendor: cisco    │ Telnet: No       │           │   │
│  │  └──────────────────┴──────────────────┘           │   │
│  │                                                     │   │
│  │  Compliance Rules                                  │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │ ✅ [CIS-1.1.2] SSH version 2 or higher     │   │   │
│  │  │    Field: management.ssh_version           │   │   │
│  │  │    Expected: 2  |  Actual: 2               │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │ ❌ [CIS-2.1.1] HTTP server disabled        │   │   │
│  │  │    Field: management.http_enabled          │   │   │
│  │  │    Expected: false  |  Actual: true        │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Component Breakdown

### 1. Hero Section (Top)

#### Left Side - Product Information
```
┌──────────────────────────────┐
│ Network Security             │  ← Large heading (56px)
│ Compliance Automation        │
│                              │
│ Analyze network device       │  ← Subtitle (18px)
│ configurations against CIS   │
│ and NIST security standards. │
└──────────────────────────────┘
```

**Style:**
- Background: Light gray (#fafafa)
- Text: Dark gray (#1a1a1a)
- Line height: 1.7

#### Right Side - Upload Form
```
┌─────────────────────────────────┐
│  Upload Configuration           │  ← Card title
│                                 │
│  Device Vendor                  │  ← Label
│  [Select vendor...       ▼]     │  ← Dropdown
│                                 │
│  Configuration File             │  ← Label
│  [Choose file...] [Browse]      │  ← File input
│  filename.txt                   │  ← Selected file
│                                 │
│  ┌───────────────────────────┐  │
│  │ Analyze Configuration     │  │  ← Primary button
│  └───────────────────────────┘  │
│                                 │
│  ⓘ Analyzing configuration...   │  ← Status message
└─────────────────────────────────┘
```

**Style:**
- Card: White (#ffffff)
- Border: 1px solid #e0e0e0
- Shadow: Soft (0 10px 25px rgba(0,0,0,0.08))
- Border radius: 12px
- Padding: 40px

### 2. Results Section (Bottom)

#### Header Bar
```
┌───────────────────────────────────────────────┐
│  Compliance Report        [Download PDF]      │
└───────────────────────────────────────────────┘
     32px bold                   Button
```

#### Metadata Grid
```
┌──────────────┬────────────────┬──────────────┐
│ UPLOAD ID    │ VENDOR         │ STATUS       │  ← Labels (13px)
│ abc-123-def  │ CISCO          │ Done         │  ← Values (18px)
└──────────────┴────────────────┴──────────────┘
```

**Status Badge Colors:**
- ✅ Done: Green background (#d4edda)
- ⚠️ Review: Yellow background (#fff3cd)
- ❌ Failed: Red background (#f8d7da)

#### Summary Cards (Grid)
```
┌────────┬────────┬────────┬──────────┐
│ TOTAL  │ PASSED │ FAILED │ CRITICAL │  ← Labels
│   8    │   4    │   3    │    2     │  ← Values (32px)
└────────┴────────┴────────┴──────────┘
  Gray     Green    Red      Red
```

**Card Style:**
- Background: #fafafa
- Border: 1px solid #e0e0e0
- Padding: 24px
- Border radius: 10px

#### Baseline Configuration (Grid)
```
┌──────────────────────┬──────────────────────┐
│ HOSTNAME             │ SSH VERSION          │
│ Core-SW-01           │ 2                    │
├──────────────────────┼──────────────────────┤
│ VENDOR               │ TELNET ENABLED       │
│ cisco                │ No                   │
└──────────────────────┴──────────────────────┘
```

**Style:**
- 2-column grid
- Key: 13px, gray
- Value: 15px, black

#### Compliance Rules (List)
```
┌─────────────────────────────────────────────┐
│ ✅  [CIS-1.1.2]                            │  ← Emoji + Rule ID
│     SSH version 2 or higher                 │  ← Rule name
│                                             │
│     Field: management.ssh_version           │  ← Details
│     Expected: 2  |  Actual: 2              │
└─────────────────────────────────────────────┘
   Green border (left side)

┌─────────────────────────────────────────────┐
│ ❌  [CIS-2.1.1]                            │
│     HTTP server disabled                    │
│                                             │
│     Field: management.http_enabled          │
│     Expected: false  |  Actual: true        │
└─────────────────────────────────────────────┘
   Red border (left side)
```

**Rule Item Styles:**
- Pass: Green left border (#27ae60)
- Fail: Red left border (#e74c3c)
- Unknown: Yellow left border (#f39c12)
- Background: #fafafa
- Padding: 20px
- Border radius: 8px

## Color Coding System

### Status Colors

**Pass (Success):**
```
✅ Green (#27ae60)
Used for: Passed rules, success messages, positive metrics
```

**Fail (Error):**
```
❌ Red (#e74c3c)
Used for: Failed rules, error messages, critical issues
```

**Unknown (Warning):**
```
⚠️ Yellow (#f39c12)
Used for: Review needed, missing data, warnings
```

**Info:**
```
ℹ️ Navy (#2c3e50)
Used for: Loading states, informational messages, buttons
```

### Background Colors

**Primary Background:**
```
#fafafa - Light gray (main page background)
```

**Secondary Background:**
```
#ffffff - White (cards, forms, highlights)
```

**Tertiary Background:**
```
#f5f5f5 - Off-white (nested cards, alternate rows)
```

## Typography Scale

```
Hero Title:        56px / 600 weight / Line height 1.1
Section Heading:   32px / 600 weight / Line height 1.2
Card Title:        24px / 600 weight / Line height 1.3
Subsection:        20px / 600 weight / Line height 1.4
Body Text:         16px / 400 weight / Line height 1.6
Form Label:        14px / 500 weight / Line height 1.5
Small Text:        13px / 400 weight / Line height 1.5
```

## Spacing System

```
Section Gap:    80px
Card Padding:   40px
Element Gap:    24px
Small Gap:      12px
Tiny Gap:       8px
```

## Interactive States

### Button States

**Normal:**
```
┌─────────────────────────┐
│ Analyze Configuration   │  Background: #2c3e50
└─────────────────────────┘  Color: white
```

**Hover:**
```
┌─────────────────────────┐
│ Analyze Configuration   │  Background: #1a252f
└─────────────────────────┘  Transform: translateY(-1px)
                             Shadow: 0 4px 6px rgba(0,0,0,0.07)
```

**Loading:**
```
┌─────────────────────────┐
│ Analyzing...           │  Background: #666
└─────────────────────────┘  Cursor: not-allowed
                             Disabled: true
```

### Form Input States

**Normal:**
```
[Select vendor...        ▼]  Border: 1px solid #e0e0e0
```

**Focus:**
```
[Select vendor...        ▼]  Border: 1px solid #2c3e50
                             Shadow: 0 0 0 3px rgba(44,62,80,0.1)
```

**Filled:**
```
[cisco                   ▼]  Border: 1px solid #e0e0e0
                             Color: #1a1a1a
```

## Responsive Behavior

### Desktop (> 1024px)
```
┌────────────────────────────────────┐
│  [Product Info]  │  [Upload Form]  │  2 columns
└────────────────────────────────────┘
```

### Tablet (640px - 1024px)
```
┌────────────────────────────────────┐
│         [Product Info]             │
├────────────────────────────────────┤
│         [Upload Form]              │  1 column
└────────────────────────────────────┘
```

### Mobile (< 640px)
```
┌──────────────────┐
│  [Product Info]  │  Smaller text
├──────────────────┤
│  [Upload Form]   │  Compact padding
└──────────────────┘
```

## Animation & Transitions

### Smooth Scroll
```javascript
resultsSection.scrollIntoView({ 
    behavior: 'smooth', 
    block: 'start' 
});
```
**Duration:** ~800ms

### Button Hover
```css
transition: all 0.2s;
transform: translateY(-1px);
```
**Duration:** 200ms

### Form Focus
```css
transition: all 0.2s;
box-shadow: 0 0 0 3px rgba(44,62,80,0.1);
```
**Duration:** 200ms

## Status Message Examples

### Success
```
┌────────────────────────────────────┐
│ ✓ Analysis complete!               │  Green background
└────────────────────────────────────┘  Green text
```

### Error
```
┌────────────────────────────────────┐
│ ✗ Upload failed: Invalid file      │  Red background
└────────────────────────────────────┘  Red text
```

### Loading
```
┌────────────────────────────────────┐
│ ⟳ Analyzing configuration...       │  Blue background
└────────────────────────────────────┘  Blue text
```

## PDF Download Flow

```
Click [Download PDF]
        ↓
Show "Generating PDF..." status
        ↓
Fetch from API
        ↓
Create blob URL
        ↓
Trigger download
        ↓
Show "PDF downloaded!" success
        ↓
Auto-hide after 3 seconds
```

## Empty States

### No Results Yet
```
┌────────────────────────────────────┐
│    Upload a configuration file     │
│    to view compliance results      │
└────────────────────────────────────┘
         (Results section hidden)
```

### After Upload
```
┌────────────────────────────────────┐
│  Compliance Report                 │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  [Full results displayed]          │
└────────────────────────────────────┘
         (Scrolled into view)
```

## File Upload Visual Flow

```
1. Initial State
   [Choose file...]  [Browse]

2. File Selected
   [sample_config.txt]  [Browse]
   filename.txt                     ← Shows below

3. Uploading
   [Analyzing...]
   ⓘ Analyzing configuration...     ← Status message

4. Complete
   [Analyze Configuration]
   ✓ Analysis complete!             ← Success message
   (Results appear below)
```

## Conclusion

This interface prioritizes:
- ✅ **Clarity** - Every element has clear purpose
- ✅ **Simplicity** - No unnecessary decoration
- ✅ **Functionality** - Direct path to goal
- ✅ **Feedback** - Always know system state
- ✅ **Accessibility** - Keyboard & screen reader friendly

**Total Visual Complexity:** Minimal
**User Cognitive Load:** Low
**Time to Completion:** Under 30 seconds
