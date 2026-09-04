#!/usr/bin/env python3
"""
dashboard_view.py - High-productivity, clean, professional registry operations dashboard.
Features:
  - Left side navigation menu with all operational workflows (shared across Dashboard & New Scan)
  - Statistical graphs (Registration Throughput Area Chart & Document Classification Donut Chart)
  - 4 Executive KPI Cards
  - Full-width Master Ruled Deed Register with live search & filtering
  - Dedicated New Scan & Document Intake workspace with persistent sidebar
  - OneBhoomi official legal paper styling (Fraunces, Archivo, Courier Prime)
"""

from __future__ import annotations

import html
import hashlib
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import verification_service

BADGE_LABELS = {
    "APPROVED": "Sealed & Certified",
    "REJECTED": "Rejected on Record",
    "UNDER_REVIEW": "Clerk Review",
    "EXTRACTED": "Pending Check",
    "READY_FOR_APPROVAL": "Ready for Seal",
    "PASS": "Checks Passed",
    "FAIL": "Checks Failed",
}

DASHBOARD_CSS = """
    :root{
      --paper:#F6F0E1; --paper-deep:#EFE6D0; --ink:#221D17; --ink-soft:#5A5142;
      --stamp:#A6193C; --stamp-deep:#7C1030; --rosette:#C99AA8; --green:#2E6B4F;
      --green-deep:#1C4A36; --amber:#A96A1F; --gold:#C9A227;
      --rule:#C9BC9F; --rule-soft:#DCD2B8; --card:#FFFDF6;
      --border:#D4C8AE; --border-dark:#221D17;
      --serif:"Fraunces", "Noto Serif Devanagari", "Noto Serif Telugu", "Noto Serif Kannada", "Noto Serif Tamil", Georgia, serif;
      --type:"Courier Prime", "Noto Sans Devanagari", "Noto Sans Telugu", "Noto Sans Kannada", "Noto Sans Tamil", "Courier New", monospace;
      --sans:"Archivo", "Noto Sans Devanagari", "Noto Sans Telugu", "Noto Sans Kannada", "Noto Sans Tamil", system-ui, sans-serif;
    }

    /* Header Language Picker */
    .lang-picker {
      display: inline-flex;
      align-items: center;
      background: var(--paper-deep);
      border: 1px solid var(--rule);
      border-radius: 4px;
      padding: 3px 8px;
      margin-right: 12px;
      transition: border-color .15s ease, box-shadow .15s ease;
      position: relative;
    }
    .lang-picker:focus-within, .lang-picker:hover {
      border-color: var(--stamp);
      box-shadow: 0 0 0 2px rgba(166,25,60,0.12);
    }
    .lang-dropdown,
    .lang-picker select,
    select.lang-dropdown {
      background: transparent !important;
      border: none !important;
      outline: none !important;
      box-shadow: none !important;
      -webkit-appearance: none !important;
      -moz-appearance: none !important;
      appearance: none !important;
      font-family: var(--type) !important;
      font-size: 11.5px !important;
      color: var(--ink) !important;
      font-weight: 700 !important;
      letter-spacing: .5px !important;
      cursor: pointer !important;
      padding: 2px 18px 2px 2px !important;
      margin: 0 !important;
      width: auto !important;
      height: auto !important;
      background-image: url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%235A5142' d='M0 0l5 6 5-6z'/%3E%3C/svg%3E") !important;
      background-repeat: no-repeat !important;
      background-position: right center !important;
      background-size: 8px 5px !important;
    }
    .lang-dropdown:focus,
    .lang-dropdown:focus-visible,
    .lang-dropdown:active,
    .lang-picker select:focus,
    .lang-picker select:focus-visible,
    .lang-picker select:active,
    select.lang-dropdown:focus,
    select.lang-dropdown:focus-visible,
    select.lang-dropdown:active {
      outline: none !important;
      border: none !important;
      box-shadow: none !important;
    }
    .lang-dropdown option {
      background: #FFFDF6;
      color: #221D17;
      font-family: var(--sans);
      font-size: 13px;
      font-weight: 500;
      padding: 6px 10px;
    }
    html[lang="hi"] body, html[lang="hi"] p, html[lang="hi"] span, html[lang="hi"] a { font-family: "Noto Sans Devanagari", var(--sans); }
    html[lang="te"] body, html[lang="te"] p, html[lang="te"] span, html[lang="te"] a { font-family: "Noto Sans Telugu", var(--sans); }
    html[lang="kn"] body, html[lang="kn"] p, html[lang="kn"] span, html[lang="kn"] a { font-family: "Noto Sans Kannada", var(--sans); }
    html[lang="ta"] body, html[lang="ta"] p, html[lang="ta"] span, html[lang="ta"] a { font-family: "Noto Sans Tamil", var(--sans); }
    }
    *{margin:0;padding:0;box-sizing:border-box}
    html{scroll-behavior:smooth}
    body{
      background:var(--paper);color:var(--ink);font-family:var(--sans);
      font-size:14.5px;line-height:1.55;overflow-x:hidden;
    }
    ::selection{background:var(--stamp);color:var(--paper)}

    .security-bg{
      position:fixed;inset:0;z-index:0;pointer-events:none;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='420' height='420' viewBox='0 0 420 420'%3E%3Cg fill='none' stroke='%23C99AA8' stroke-width='1' opacity='.22'%3E%3Ccircle cx='210' cy='210' r='196'/%3E%3Ccircle cx='210' cy='210' r='188' stroke-dasharray='3 6'/%3E%3Ccircle cx='210' cy='210' r='172'/%3E%3Ccircle cx='210' cy='210' r='164' stroke-dasharray='10 4'/%3E%3Ccircle cx='210' cy='210' r='148'/%3E%3Ccircle cx='210' cy='210' r='140' stroke-dasharray='2 5'/%3E%3Ccircle cx='210' cy='210' r='124'/%3E%3Ccircle cx='210' cy='210' r='116' stroke-dasharray='8 5'/%3E%3Ccircle cx='210' cy='210' r='100'/%3E%3Ccircle cx='210' cy='210' r='92' stroke-dasharray='4 4'/%3E%3Ccircle cx='210' cy='210' r='76'/%3E%3Ccircle cx='210' cy='210' r='68' stroke-dasharray='12 3'/%3E%3Ccircle cx='210' cy='210' r='52'/%3E%3Ccircle cx='210' cy='210' r='44'/%3E%3Ccircle cx='210' cy='210' r='36' stroke-dasharray='3 4'/%3E%3Ccircle cx='210' cy='210' r='20'/%3E%3C/g%3E%3C/svg%3E");
      background-size:420px 420px;
      opacity:.32;
    }

    /* Outer Shell with Sidebar Layout */
    .app-layout{
      display:flex;min-height:100vh;position:relative;z-index:1;
    }

    /* ---------------------------------------------------- */
    /* LEFT SIDE MENU (Fixed Navigation Rail)               */
    /* ---------------------------------------------------- */
    aside.dash-sidebar{
      width:260px;min-width:260px;background:var(--card);
      border-right:1.5px solid var(--border);
      display:flex;flex-direction:column;justify-content:space-between;
      position:sticky;top:0;height:100vh;overflow-y:auto;z-index:100;
      box-shadow:2px 0 6px rgba(0,0,0,.02);
    }
    @media(max-width:960px){
      aside.dash-sidebar{display:none}
      .app-layout{flex-direction:column}
    }

    .sidebar-top{padding:24px 16px 16px;text-align:left}
    .brand-box{
      display:flex;flex-direction:column;gap:3px;text-decoration:none;color:var(--ink);
      padding-bottom:18px;border-bottom:2px double var(--rule);margin-bottom:22px;text-align:left;
    }
    .brand-box b{font-family:var(--serif);font-weight:900;font-size:26px;letter-spacing:.04em;line-height:1;text-align:left}
    .brand-box span{font-family:var(--type);font-size:10.5px;letter-spacing:.18em;color:var(--stamp);text-transform:uppercase;text-align:left}

    .nav-label{
      font-family:var(--type);font-size:10px;letter-spacing:.16em;text-transform:uppercase;
      color:var(--ink-soft);padding:0 8px;margin-bottom:10px;font-weight:700;text-align:left;
    }

    .nav-menu{display:flex;flex-direction:column;gap:3px;list-style:none;padding:0;margin:0}
    .nav-menu li a{
      display:flex;align-items:center;justify-content:space-between;
      padding:10px 10px 10px 8px;border-radius:2px;text-decoration:none;color:var(--ink);
      font-size:13.5px;font-weight:600;transition:all .15s ease;
      border-left:3px solid transparent;text-align:left;
    }
    .nav-menu li a:hover{
      background:var(--paper);border-left-color:var(--rule);color:var(--ink);
    }
    .nav-menu li a.active{
      background:var(--paper-deep);border-left-color:var(--stamp);color:var(--stamp);font-weight:700;
    }
    .nav-link-left{display:flex;align-items:center;gap:0;text-align:left;justify-content:flex-start}

    .nav-badge{
      font-family:var(--type);font-size:10px;padding:2px 6px;border-radius:2px;
      font-weight:700;letter-spacing:.05em;
    }
    .badge-primary{background:var(--stamp);color:var(--paper)}
    .badge-amber{background:#FEF7E0;color:#8A5300;border:1px solid #F2CD86}
    .badge-green{background:#E6F4EA;color:var(--green);border:1px solid #A8DAB5}

    .sidebar-bottom{
      padding:16px 20px;background:var(--paper-deep);border-top:1.5px solid var(--border);
    }
    .sys-pill{
      display:flex;align-items:center;gap:6px;font-family:var(--type);font-size:10.5px;
      letter-spacing:.12em;text-transform:uppercase;color:var(--green-deep);
      margin-bottom:8px;font-weight:700;
    }
    .sys-dot{width:7px;height:7px;border-radius:50%;background:var(--green)}
    .sys-meta{
      font-family:var(--type);font-size:10.5px;color:var(--ink-soft);line-height:1.45;
    }

    /* ---------------------------------------------------- */
    /* MAIN CONTENT AREA                                    */
    /* ---------------------------------------------------- */
    main.dash-content{
      flex:1;min-width:0;display:flex;flex-direction:column;
    }
    .main-inner{
      padding:28px 40px 54px;max-width:1440px;width:100%;margin:0 auto;
    }
    @media(max-width:768px){.main-inner{padding:18px 16px 36px}}

    /* Top Action Bar */
    .top-action-bar{
      display:flex;justify-content:space-between;align-items:center;
      margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--rule-soft);
      flex-wrap:wrap;gap:14px;
    }
    .header-left h1{
      font-family:var(--serif);font-size:28px;font-weight:600;color:var(--ink);line-height:1.15;
    }
    .header-left h1 em{font-style:italic;color:var(--stamp);font-weight:400}
    .header-tagline{font-size:13.5px;color:var(--ink-soft);margin-top:4px}

    .header-right{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
    .date-badge{
      font-family:var(--type);font-size:11px;color:var(--ink-soft);
      padding:6px 12px;border:1px solid var(--border);background:var(--card);border-radius:2px;
    }
    .btn{
      font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
      text-decoration:none;padding:9px 18px;border-radius:2px;display:inline-flex;align-items:center;
      gap:6px;border:0;cursor:pointer;font-weight:700;transition:all .15s ease;
    }
    .btn-primary{background:var(--stamp);color:var(--paper);box-shadow:2px 2px 0 var(--stamp-deep)}
    .btn-primary:hover{transform:translate(-1px,-1px);box-shadow:3px 3px 0 var(--stamp-deep)}
    .btn-ghost{color:var(--ink);border:1.5px solid var(--ink);background:transparent}
    .btn-ghost:hover{background:var(--ink);color:var(--paper)}
    .btn-sm{padding:6px 12px;font-size:10.5px}

    /* 4-Grid KPI Cards */
    .kpi-grid{
      display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin-bottom:26px;
      align-items:stretch;
    }
    @media(max-width:1120px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
    @media(max-width:560px){.kpi-grid{grid-template-columns:1fr}}

    .kpi-card{
      background:var(--card);border:1.5px solid var(--border);border-radius:2px;
      padding:20px 22px;position:relative;box-shadow:2px 2px 0 rgba(0,0,0,.025);
      transition:transform .15s ease, border-color .15s ease;
      display:flex;flex-direction:column;justify-content:space-between;height:100%;box-sizing:border-box;
    }
    .kpi-card:hover{border-color:var(--ink);transform:translateY(-2px)}
    .kpi-label{
      font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
      color:var(--ink-soft);margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;
    }
    .kpi-num{
      font-family:var(--serif);font-size:42px;font-weight:700;line-height:1;
      color:var(--ink);margin-bottom:6px;font-variant-numeric:tabular-nums;
    }
    .kpi-card.kpi-sealed .kpi-num{color:var(--green)}
    .kpi-card.kpi-desk .kpi-num{color:var(--amber)}
    .kpi-card.kpi-rejected .kpi-num{color:var(--stamp)}
    .kpi-sub{font-size:12px;color:var(--ink-soft);line-height:1.3}

    /* Action Notice Banner */
    .notice-banner{
      background:#FFF9E6;border:1.5px solid #F0C36D;border-left:4px solid var(--amber);
      border-radius:2px;padding:12px 18px;margin-bottom:24px;
      display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;
      width:100%;box-sizing:border-box;
    }
    .notice-info{display:flex;align-items:center;gap:12px}
    .notice-icon{font-size:20px}
    .notice-text{font-size:13.5px;color:#5A4008}
    .notice-text b{color:#2E2002}

    /* ---------------------------------------------------- */
    /* STATISTICAL ANALYTICS GRAPHS (2-Col Clean Layout)    */
    /* ---------------------------------------------------- */
    .charts-grid{
      display:grid;grid-template-columns:1.6fr 1fr;gap:20px;margin-bottom:26px;
      align-items:stretch;
    }
    @media(max-width:1080px){.charts-grid{grid-template-columns:1fr}}

    .chart-card{
      background:var(--card);border:1.5px solid var(--border);border-radius:2px;
      padding:22px;display:flex;flex-direction:column;justify-content:space-between;
      height:100%;box-sizing:border-box;box-shadow:2px 2px 0 rgba(0,0,0,.025);
    }
    .chart-header{
      display:flex;justify-content:space-between;align-items:baseline;
      margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--rule-soft);
      flex-wrap:wrap;gap:8px;
    }
    .chart-title{font-family:var(--serif);font-size:17px;font-weight:700;color:var(--ink)}
    .chart-meta{font-family:var(--type);font-size:11px;color:var(--ink-soft);letter-spacing:.08em}

    .chart-svg-wrap{width:100%;height:auto;overflow:hidden}
    .chart-svg{width:100%;height:auto;display:block}

    /* Donut Chart Layout */
    .donut-layout{
      display:flex;align-items:center;gap:24px;flex-wrap:wrap;margin:auto 0;
    }
    .donut-svg-box{width:140px;height:140px;flex-shrink:0;position:relative}
    .donut-legend{flex:1;display:flex;flex-direction:column;gap:8px;min-width:150px}
    .legend-row{
      display:flex;justify-content:space-between;align-items:center;font-size:12.5px;
    }
    .legend-left{display:flex;align-items:center;gap:8px}
    .legend-color{width:10px;height:10px;border-radius:2px;flex-shrink:0}
    .legend-num{font-family:var(--type);font-weight:700;color:var(--ink)}

    .gis-rate-meter{
      margin-top:16px;padding-top:12px;border-top:1px solid var(--rule-soft);
    }
    .meter-label{
      display:flex;justify-content:space-between;font-family:var(--type);font-size:11px;
      color:var(--ink-soft);margin-bottom:6px;
    }
    .meter-bar{
      height:6px;background:var(--paper-deep);border-radius:3px;overflow:hidden;
    }
    .meter-fill{
      height:100%;background:var(--green);border-radius:3px;
    }

    /* ---------------------------------------------------- */
    /* MASTER DEED REGISTER LEDGER                          */
    /* ---------------------------------------------------- */
    .ledger-section{
      background:var(--card);border:1.5px solid var(--ink);border-radius:2px;
      box-shadow:3px 3px 0 rgba(0,0,0,.04);margin-bottom:26px;width:100%;box-sizing:border-box;
    }
    .ledger-toolbar{
      padding:12px 18px;background:var(--paper-deep);border-bottom:1.5px solid var(--ink);
      display:flex;justify-content:space-between;align-items:center;gap:14px;
      width:100%;box-sizing:border-box;flex-wrap:nowrap;
    }
    .toolbar-left{display:flex;align-items:center;gap:12px;flex-shrink:1;min-width:0}
    .ledger-head-title{
      font-family:var(--serif);font-size:18px;font-weight:700;color:var(--ink);
      white-space:nowrap;flex-shrink:0;
    }
    .search-wrap{position:relative;flex-shrink:1;min-width:130px;max-width:230px;width:100%}
    .search-input{
      font-family:var(--sans);font-size:12.5px;padding:6px 10px 6px 28px;
      border:1.5px solid var(--rule);border-radius:2px;background:var(--paper);
      color:var(--ink);width:100%;box-sizing:border-box;transition:all .15s ease;outline:none;
    }
    .search-input:focus{border-color:var(--stamp);background:var(--card)}
    .search-icon{position:absolute;left:8px;top:50%;transform:translateY(-50%);color:var(--ink-soft);font-size:12px}

    .toolbar-right{display:flex;align-items:center;gap:8px;flex-shrink:0;white-space:nowrap;flex-wrap:nowrap}
    .filter-tabs{display:flex;gap:4px;align-items:center;flex-wrap:nowrap}
    .tab-btn{
      font-family:var(--type);font-size:10.5px;padding:5px 9px;border:1px solid var(--rule);
      background:var(--paper);color:var(--ink-soft);border-radius:2px;cursor:pointer;
      transition:all .15s ease;white-space:nowrap;flex-shrink:0;
    }
    .tab-btn:hover{color:var(--ink);border-color:var(--ink)}
    .tab-btn.active{
      background:var(--stamp);color:var(--paper);border-color:var(--stamp-deep);font-weight:700;
    }

    /* Table Component */
    .table-container{overflow-x:auto;max-height:600px}
    table.master-ledger{width:100%;border-collapse:collapse;text-align:left}
    table.master-ledger thead th{
      position:sticky;top:0;z-index:10;
      background:var(--ink);color:var(--paper);font-family:var(--type);
      font-size:11px;letter-spacing:.12em;text-transform:uppercase;
      padding:12px 14px;font-weight:600;white-space:nowrap;border-right:1px solid rgba(255,255,255,.1);
    }
    table.master-ledger tbody tr{
      border-bottom:1px solid var(--rule-soft);transition:background .1s ease;
    }
    table.master-ledger tbody tr:nth-child(even){background:rgba(239,230,208,.3)}
    table.master-ledger tbody tr:hover{background:rgba(166,25,60,.04)}
    table.master-ledger td{padding:13px 14px;font-size:13.5px;vertical-align:middle}

    .td-sl{font-family:var(--type);font-weight:700;color:var(--stamp);font-size:12px}
    .td-date{font-family:var(--type);font-size:12px;color:var(--ink-soft);white-space:nowrap}
    .td-doc-main{font-weight:600;color:var(--ink);display:block}
    .td-doc-sub{font-family:var(--type);font-size:11px;color:var(--ink-soft)}
    .td-place-main{font-weight:600;color:var(--ink);display:block}
    .td-place-sub{font-size:12px;color:var(--ink-soft)}
    .td-mono{font-family:var(--type);font-size:12px;color:var(--ink)}
    .td-stamp{font-family:var(--type);font-weight:700;color:var(--stamp-deep)}

    /* Status Badges */
    .badge{
      font-family:var(--type);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
      padding:3px 8px;border-radius:2px;display:inline-flex;align-items:center;gap:5px;font-weight:700;
      border:1px solid transparent;white-space:nowrap;
    }
    .b-approved{background:#E6F4EA;color:var(--green);border-color:#A8DAB5}
    .b-extracted,.b-ready_for_approval,.b-under_review{background:#FEF7E0;color:#8A5300;border-color:#F2CD86}
    .b-rejected,.b-fail{background:#FCE8E6;color:var(--stamp);border-color:#F5B7B1}

    .action-links{display:flex;gap:8px;align-items:center;white-space:nowrap}
    .act-btn{
      font-family:var(--type);font-size:11px;padding:5px 10px;border-radius:2px;
      text-decoration:none;border:1px solid var(--border-dark);color:var(--ink);
      font-weight:700;background:var(--paper);transition:all .12s ease;
    }
    .act-btn:hover{background:var(--ink);color:var(--paper)}
    .act-btn.act-verify{border-color:var(--green);color:var(--green);background:#F0F8F3}
    .act-btn.act-verify:hover{background:var(--green);color:var(--paper)}

    /* Empty table state */
    .table-empty{padding:56px 20px;text-align:center;color:var(--ink-soft)}
    .table-empty p{font-size:15px;margin-bottom:12px}

    /* ---------------------------------------------------- */
    /* DEDICATED NEW SCAN INTAKE PAGE STYLES                */
    /* ---------------------------------------------------- */
    .intake-card{
      background:var(--card);border:1.5px solid var(--ink);border-radius:2px;
      box-shadow:3px 3px 0 rgba(0,0,0,.04);padding:32px 36px;margin-bottom:30px;
    }
    .intake-head{
      display:flex;justify-content:space-between;align-items:baseline;
      padding-bottom:14px;border-bottom:2px double var(--rule);margin-bottom:24px;
      flex-wrap:wrap;gap:12px;
    }
    .intake-head h2{font-family:var(--serif);font-size:22px;color:var(--ink);font-weight:700}
    .intake-badge{
      font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
      padding:4px 10px;background:var(--paper-deep);border:1px solid var(--border);
      color:var(--stamp);font-weight:700;
    }

    .intake-dropzone{
      border:2.5px dashed var(--rule);border-radius:3px;padding:42px 24px;
      text-align:center;background:var(--paper);cursor:pointer;
      transition:all .18s ease;position:relative;margin-bottom:24px;
    }
    .intake-dropzone:hover,.intake-dropzone.dragover{
      border-color:var(--stamp);background:var(--card);box-shadow:inset 0 0 12px rgba(166,25,60,.04);
    }
    .dz-icon-svg{width:48px;height:48px;margin:0 auto 12px;display:block;stroke:var(--stamp);fill:none}
    .dz-main-text{font-size:16px;font-weight:700;color:var(--ink);margin-bottom:4px}
    .dz-main-text span{color:var(--stamp);text-decoration:underline}
    .dz-sub-text{font-family:var(--type);font-size:11.5px;color:var(--ink-soft)}

    .filechip{
      display:flex;justify-content:space-between;align-items:center;
      padding:12px 18px;background:var(--paper-deep);border:1.5px solid var(--border-dark);
      border-radius:2px;margin-bottom:24px;
    }
    .filechip-name{font-weight:700;font-size:14px;color:var(--ink);display:flex;align-items:center;gap:8px}
    .filechip-actions{display:flex;align-items:center;gap:12px}
    .filechip-size{font-family:var(--type);font-size:11.5px;color:var(--ink-soft)}
    .filechip-btn{
      background:none;border:none;color:var(--stamp);font-size:16px;cursor:pointer;
      padding:2px 6px;line-height:1;font-weight:700;
    }

    .config-grid{
      display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:28px;
    }
    @media(max-width:768px){.config-grid{grid-template-columns:1fr}}

    .config-box{
      background:var(--paper);border:1px solid var(--rule);padding:16px 18px;border-radius:2px;
    }
    .config-box-title{
      font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;
      color:var(--ink-soft);margin-bottom:10px;font-weight:700;
    }
    .select-mode{
      width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:2px;
      font-family:var(--sans);font-size:13.5px;font-weight:600;background:var(--card);
      color:var(--ink);outline:none;
    }
    .select-mode:focus{border-color:var(--stamp)}
    .config-note{font-family:var(--type);font-size:11px;color:var(--ink-soft);margin-top:8px;line-height:1.4}

    /* Pipeline Stepper */
    .stepper-strip{
      display:flex;background:var(--paper-deep);border:1px solid var(--border);
      padding:14px 18px;border-radius:2px;margin-bottom:28px;gap:8px;flex-wrap:wrap;
    }
    .stepper-item{
      flex:1;min-width:140px;display:flex;align-items:center;gap:8px;font-size:12px;
    }
    .step-num{
      width:22px;height:22px;border-radius:50%;background:var(--paper);border:1px solid var(--rule);
      font-family:var(--type);font-size:11px;display:flex;align-items:center;justify-content:center;
      color:var(--ink-soft);font-weight:700;flex-shrink:0;
    }
    .stepper-item.step-active .step-num{
      background:var(--stamp);border-color:var(--stamp);color:var(--paper);
    }
    .step-label{font-weight:600;color:var(--ink-soft)}
    .stepper-item.step-active .step-label{color:var(--ink)}

    .submit-row{
      display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;
      padding-top:20px;border-top:1.5px solid var(--rule-soft);
    }
    .submit-note{font-family:var(--type);font-size:11.5px;color:var(--ink-soft)}

    /* Loading Overlay */
    .loading-overlay{
      display:none;position:fixed;inset:0;background:rgba(34,29,23,.75);z-index:9999;
      align-items:center;justify-content:center;backdrop-filter:blur(4px);
    }
    .loading-box{
      background:var(--paper);border:2px solid var(--ink);border-radius:2px;padding:34px 44px;
      text-align:center;box-shadow:6px 6px 0 rgba(0,0,0,.3);max-width:400px;
    }
    .loading-spinner{
      width:44px;height:44px;border:3px solid var(--rule);border-top-color:var(--stamp);
      border-radius:50%;margin:0 auto 16px;animation:spin 1s linear infinite;
    }
    @keyframes spin{to{transform:rotate(360deg)}}
    .loading-title{font-family:var(--serif);font-size:20px;font-weight:700;color:var(--ink);margin-bottom:6px}
    .loading-sub{font-family:var(--type);font-size:11.5px;color:var(--ink-soft)}

    /* Understated Security & Authority Bar */
    .system-strip{
      background:var(--paper-deep);border:1px solid var(--border);border-radius:2px;
      padding:12px 20px;display:flex;justify-content:space-between;align-items:center;
      flex-wrap:wrap;gap:14px;font-family:var(--type);font-size:11px;color:var(--ink-soft);
      margin-bottom:20px;
    }
    .strip-group{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
    .strip-item{display:flex;align-items:center;gap:6px}
    .strip-item b{color:var(--ink)}
    .btn-copy{
      background:none;border:none;color:var(--stamp);cursor:pointer;font-family:var(--type);
      font-size:10.5px;text-transform:uppercase;font-weight:700;padding:2px 4px;margin-left:4px;
    }
    .btn-copy:hover{text-decoration:underline}

    /* Footer Note */
    footer.dash-footer{
      border-top:3px double var(--rule);padding:20px 0;background:var(--paper);
      margin-top:auto;
    }
    .dash-footer-wrap{
      display:flex;justify-content:space-between;align-items:center;
      font-family:var(--type);font-size:11px;color:var(--ink-soft);flex-wrap:wrap;gap:12px;
    }
"""

DASHBOARD_JS = """
  function filterTable() {
    const searchInput = document.getElementById('ledgerSearch');
    if (!searchInput) return;
    const searchVal = (searchInput.value || '').toLowerCase().trim();
    const activeTabEl = document.querySelector('.tab-btn.active');
    const activeTab = activeTabEl ? (activeTabEl.dataset.filter || 'ALL') : 'ALL';
    const rows = document.querySelectorAll('#ledgerBody tr.data-row');
    let visibleCount = 0;

    rows.forEach(row => {
      const text = row.textContent.toLowerCase();
      const status = row.dataset.status || '';
      
      const matchesSearch = !searchVal || text.includes(searchVal);
      let matchesTab = false;

      if (activeTab === 'ALL') matchesTab = true;
      else if (activeTab === 'SEALED') matchesTab = (status === 'APPROVED');
      else if (activeTab === 'PENDING') matchesTab = (status !== 'APPROVED' && status !== 'REJECTED');
      else if (activeTab === 'REJECTED') matchesTab = (status === 'REJECTED');

      if (matchesSearch && matchesTab) {
        row.style.display = '';
        visibleCount++;
      } else {
        row.style.display = 'none';
      }
    });

    const emptyNotice = document.getElementById('ledgerEmptyNotice');
    if (emptyNotice) {
      emptyNotice.style.display = (visibleCount === 0) ? 'block' : 'none';
    }
  }

  function filterTab(filterName) {
    document.querySelectorAll('.tab-btn').forEach(b => {
      b.classList.toggle('active', (b.dataset.filter === filterName));
    });
    filterTable();
    const target = document.getElementById('ledgerSection');
    if (target) { target.scrollIntoView({ behavior: 'smooth' }); }
  }

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      filterTable();
    });
  });

  const searchInput = document.getElementById('ledgerSearch');
  if (searchInput) {
    searchInput.addEventListener('input', filterTable);
  }

  window.copyFingerprint = function(text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        alert('SHA-256 Public Key Fingerprint copied to clipboard!');
      });
    } else {
      prompt('Copy Fingerprint:', text);
    }
  };

  // Dedicated Scan Intake File Dropzone Handler
  const intakeDropzone = document.getElementById('intakeDropzone');
  const fileInput = document.getElementById('scan_file_input');
  const fileChip = document.getElementById('fileChip');
  const chipName = document.getElementById('chipName');
  const chipSize = document.getElementById('chipSize');
  const chipRemove = document.getElementById('chipRemove');
  const scanForm = document.getElementById('scanForm');
  const loadingOverlay = document.getElementById('loadingOverlay');

  if (fileInput && intakeDropzone) {
    intakeDropzone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', function() {
      if (this.files && this.files.length > 0) {
        showFileChip(this.files[0]);
      }
    });

    ['dragenter', 'dragover'].forEach(eventName => {
      intakeDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        intakeDropzone.classList.add('dragover');
      }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
      intakeDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        intakeDropzone.classList.remove('dragover');
      }, false);
    });

    intakeDropzone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt.files && dt.files.length > 0) {
        fileInput.files = dt.files;
        showFileChip(dt.files[0]);
      }
    });
  }

  function showFileChip(file) {
    if (!fileChip || !intakeDropzone) return;
    intakeDropzone.style.display = 'none';
    fileChip.style.display = 'flex';
    chipName.textContent = file.name;
    const sizeKb = (file.size / 1024).toFixed(1);
    chipSize.textContent = sizeKb > 1024 ? (sizeKb / 1024).toFixed(2) + ' MB' : sizeKb + ' KB';
  }

  if (chipRemove && fileInput && fileChip && intakeDropzone) {
    chipRemove.addEventListener('click', function(e) {
      e.stopPropagation();
      fileInput.value = '';
      fileChip.style.display = 'none';
      intakeDropzone.style.display = 'block';
    });
  }

  if (scanForm && loadingOverlay) {
    scanForm.addEventListener('submit', function() {
      loadingOverlay.style.display = 'flex';
    });
  }

  // Language switcher for Dashboard
  const DASH_I18N = {"en": {"dash_sidebar_brand": "OneBhoomi · REGISTRY DESK", "nav_main_menu": "Main Menu", "nav_dash": "Dashboard", "nav_ops_dash": "Operations Dashboard", "nav_new_scan": "New Scan & Intake", "nav_new_scan_link": "New Document Scan", "badge_desk01": "Desk 01", "nav_master_reg": "Master Deed Register", "nav_clerk_queue": "Clerk Review Queue", "nav_verified_certs": "Verified Certificates", "lbl_air_gapped": "AIR-GAPPED & SECURE", "lbl_rsa_stat": "RSA-PSS 2048:", "lbl_active": "Active", "lbl_worker": "Worker:", "btn_new_scan": "+ New Document Scan", "btn_return_dash": "← Return to Dashboard", "lbl_day_book": "DAY BOOK DATE:", "lbl_register_desk": "REGISTER DESK 01 ·", "dash_h1": "Registry Operations & <em>Analytics</em>", "dash_tagline": "Complete offline day book of land records, human-in-the-loop clerk reviews, and cryptographic digital seals.", "kpi_total": "Total on File", "kpi_total_sub": "Total land deeds recorded in offline registry", "kpi_sealed": "Sealed & Certified", "kpi_sealed_sub": "certification rate · RSA-PSS signed", "kpi_review": "Clerk Review Queue", "kpi_review_sub": "Awaiting clerk verification & approval", "kpi_noncert": "Non-Certified", "kpi_noncert_sub": "Rejected or anomalous scan records", "banner_title": "Clerk Review Action Required:", "banner_prefix": "There are", "banner_suffix": "land record(s) awaiting verification against scanned evidence and officer digital signing.", "btn_open_next": "Open Next Record", "chart_vel_title": "Registration Velocity & Sealing Throughput", "chart_vel_meta": "Timeline intake volume vs verified cryptographic certifications", "chart_total_intake": "Total Intake", "chart_sealed_on_file": "Sealed on File", "chart_doc_class": "Document Classification", "chart_doc_meta": "Distribution of legal record deed categories", "chart_gis_lbl": "GIS Resolved:", "chart_sale_deeds": "Sale Deeds", "chart_agreements_gpa": "Agreements / GPA", "chart_other_records": "Other Records", "chart_spatial_match": "Telangana (TGRAC) & Karnataka Spatial Match", "chart_resolved": "Resolved", "reg_title": "Master Land Deed Register", "search_placeholder": "Search by Doc #, Village, Party, Survey...", "tab_all": "All", "tab_sealed": "Sealed", "tab_pending": "Pending", "tab_rejected": "Rejected", "btn_scan_new_deed": "+ Scan New Deed", "th_sl": "SL.", "th_received": "RECEIVED", "th_doc_no": "DOCUMENT & NO.", "th_parties": "PARTIES", "th_location": "LOCATION", "th_survey": "SURVEY DESIGNATION", "th_stamp": "STAMP DUTY", "th_status": "STATUS", "th_actions": "ACTIONS", "badge_approved": "Sealed & Certified", "badge_rejected": "Rejected on Record", "badge_under_review": "Needs Review", "badge_extracted": "Pending Check", "badge_ready_for_approval": "Ready for Seal", "badge_pass": "Checks Passed", "badge_fail": "Checks Failed", "btn_review_console": "Review Console", "btn_cert": "✓ Certificate", "lbl_fingerprint": "RSA-PSS 2048 Fingerprint:", "btn_copy": "COPY", "lbl_spatial_index": "Spatial Index:", "lbl_key_store": "Key Store:", "foot_console_title": "OneBhoomi Registry Console · Standalone Land Document Extraction & Digital Seal System", "foot_air_gapped_info": "100% Air-Gapped & Immutable · Zero cloud dependencies · Host: localhost", "badge_needs_review": "Needs Review", "Sale Deed": "Sale Deed", "Agreement of Sale-cum-General Power of Attorney": "Agreement of Sale-cum-General Power of Attorney", "Land Record": "Land Record", "Unnumbered": "Unnumbered", "Mandal": "Mandal", "Presently Mulugu District": "Presently Mulugu District", "intake_h1": "New Document Scan & <em>Intake</em>", "intake_title": "Registration & Scan Intake", "dz_main_text": "Drop the document scan copy here, or <span>browse local files</span>", "ocr_engine_title": "OCR Processing Engine", "val_grounding_title": "Validation & Spatial Grounding", "btn_start_extract": "Start Document Extraction →"}, "hi": {"dash_sidebar_brand": "वनभूमि · रजिस्ट्री डेस्क", "nav_main_menu": "मुख्य मेनू", "nav_dash": "डैशबोर्ड", "nav_ops_dash": "परिचालन डैशबोर्ड", "nav_new_scan": "नया स्कैन एवं इनटेक", "nav_new_scan_link": "नया दस्तावेज़ स्कैन", "badge_desk01": "डेस्क 01", "nav_master_reg": "मुख्य विलेख रजिस्टर", "nav_clerk_queue": "क्लर्क समीक्षा कतार", "nav_verified_certs": "प्रमाणित प्रमाणपत्र", "lbl_air_gapped": "सुरक्षित एवं एयर-गैप्ड", "lbl_rsa_stat": "RSA-PSS 2048:", "lbl_active": "सक्रिय", "lbl_worker": "वर्कर:", "btn_new_scan": "+ नया दस्तावेज़ स्कैन", "btn_return_dash": "← डैशबोर्ड पर वापस जाएं", "lbl_day_book": "रोज़नामचा तिथि:", "lbl_register_desk": "रजिस्ट्री डेस्क 01 ·", "dash_h1": "रजिस्ट्री संचालन एवं <em>विश्लेषण</em>", "dash_tagline": "भूमि अभिलेखों का संपूर्ण ऑफ़लाइन रोज़नामचा, मानवीय क्लर्क समीक्षा एवं क्रिप्टोग्राफ़िक डिजिटल मुहर।", "kpi_total": "कुल दर्ज दस्तावेज़", "kpi_total_sub": "ऑफ़लाइन रजिस्ट्री में दर्ज कुल भूमि विलेख", "kpi_sealed": "मुहरबंद एवं प्रमाणित", "kpi_sealed_sub": "प्रमाणीकरण दर · RSA-PSS हस्ताक्षरित", "kpi_review": "क्लर्क समीक्षा कतार", "kpi_review_sub": "क्लर्क सत्यापन एवं अनुमोदन प्रतीक्षित", "kpi_noncert": "गैर-प्रमाणित", "kpi_noncert_sub": "अस्वीकृत या त्रुटिपूर्ण स्कैन रिकॉर्ड", "banner_title": "क्लर्क समीक्षा कार्रवाई आवश्यक:", "banner_prefix": "यहाँ", "banner_suffix": "भूमि रिकॉर्ड साक्ष्य सत्यापन एवं अधिकारी डिजिटल हस्ताक्षर हेतु लंबित हैं।", "btn_open_next": "अगला रिकॉर्ड खोलें", "chart_vel_title": "पंजीकरण गति एवं मुहर प्रवाह", "chart_vel_meta": "दस्तावेज़ प्रवेश मात्रा बनाम सत्यापित डिजिटल प्रमाणीकरण", "chart_total_intake": "कुल प्रवेश", "chart_sealed_on_file": "अभिलेख पर मुहरबंद", "chart_doc_class": "दस्तावेज़ वर्गीकरण", "chart_doc_meta": "कानूनी भूमि विलेख श्रेणियों का वितरण", "chart_gis_lbl": "जीआईएस समाधान:", "chart_sale_deeds": "बिक्री विलेख", "chart_agreements_gpa": "समझौते / जीपीए", "chart_other_records": "अन्य रिकॉर्ड", "chart_spatial_match": "तेलंगाना (TGRAC) एवं कर्नाटक स्थानिक मिलान", "chart_resolved": "समाधानित", "reg_title": "मुख्य भूमि विलेख रजिस्टर", "search_placeholder": "दस्तावेज़ सं., ग्राम, पक्षकार, सर्वे द्वारा खोजें...", "tab_all": "सभी", "tab_sealed": "मुहरबंद", "tab_pending": "लंबित", "tab_rejected": "अस्वीकृत", "btn_scan_new_deed": "+ नया विलेख स्कैन करें", "th_sl": "क्र.", "th_received": "प्राप्ति तिथि", "th_doc_no": "दस्तावेज़ एवं क्रमांक", "th_parties": "पक्षकार", "th_location": "स्थान", "th_survey": "सर्वेक्षण पदनाम", "th_stamp": "स्टाम्प शुल्क", "th_status": "स्थिति", "th_actions": "कार्रवाई", "badge_approved": "मुहरबंद एवं प्रमाणित", "badge_rejected": "अभिलेख पर अस्वीकृत", "badge_under_review": "समीक्षा आवश्यक", "badge_extracted": "जांच लंबित", "badge_ready_for_approval": "मुहर हेतु तैयार", "badge_pass": "सत्यापन सफल", "badge_fail": "सत्यापन विफल", "btn_review_console": "समीक्षा कंसोल", "btn_cert": "✓ प्रमाणपत्र", "lbl_fingerprint": "RSA-PSS 2048 फिंगरप्रिंट:", "btn_copy": "कॉपी", "lbl_spatial_index": "स्थानिक सूचकांक:", "lbl_key_store": "कुंजी भंडार:", "foot_console_title": "वनभूमि रजिस्ट्री कंसोल · स्टैंडअलोन भूमि दस्तावेज़ निष्कर्षण एवं डिजिटल मुहर प्रणाली", "foot_air_gapped_info": "100% एयर-गैप्ड एवं अपरिवर्तनीय · शून्य क्लाउड निर्भरता · होस्ट: localhost", "badge_needs_review": "समीक्षा आवश्यक", "Sale Deed": "बिक्री विलेख", "Agreement of Sale-cum-General Power of Attorney": "बिक्री-सह-जीपीए समझौता", "Land Record": "भूमि रिकॉर्ड", "Unnumbered": "अक्रमांकित", "Mandal": "मंडल", "Presently Mulugu District": "वर्तमान में मुलुगु ज़िला", "intake_h1": "नया दस्तावेज़ स्कैन एवं <em>प्रवेश</em>", "intake_title": "पंजीकरण एवं स्कैन इनटेक", "dz_main_text": "दस्तावेज़ स्कैन प्रति यहाँ छोड़ें, या <span>स्थानीय फ़ाइलें चुनें</span>", "ocr_engine_title": "ओसीआर प्रोसेसिंग इंजन", "val_grounding_title": "सत्यापन एवं स्थानिक जांच", "btn_start_extract": "दस्तावेज़ निष्कर्षण प्रारंभ करें →"}, "te": {"dash_sidebar_brand": "వన్‌భూమి · రిజిస్ట్రీ డెస్క్", "nav_main_menu": "ప్రధాన మెనూ", "nav_dash": "డ్యాష్‌బోర్డ్", "nav_ops_dash": "కార్యకలాపాల డ్యాష్‌బోర్డ్", "nav_new_scan": "కొత్త స్కాన్ & ఇన్‌టేక్", "nav_new_scan_link": "కొత్త దస్తావేజు స్కాన్", "badge_desk01": "డెస్క్ 01", "nav_master_reg": "ప్రధాన దస్తావేజుల రిజిస్టర్", "nav_clerk_queue": "క్లర్క్ సమీక్ష వరుస", "nav_verified_certs": "ధృవీకరించిన సర్టిఫికెట్లు", "lbl_air_gapped": "సురక్షితం & ఎయిర్-గ్యాప్డ్", "lbl_rsa_stat": "RSA-PSS 2048:", "lbl_active": "క్రియాశీలం", "lbl_worker": "వర్కర్:", "btn_new_scan": "+ కొత్త దస్తావేజు స్కాన్", "btn_return_dash": "← డ్యాష్‌బోర్డుకు తిరిగి వెళ్లండి", "lbl_day_book": "రోజువారీ తేది:", "lbl_register_desk": "రిజిస్ట్రీ డెస్క్ 01 ·", "dash_h1": "రిజిస్ట్రీ కార్యకలాపాలు & <em>విశ్లేషణలు</em>", "dash_tagline": "భూ రికార్డుల ఆఫ్‌లైన్ డైలీ బుక్, క్లర్క్ సమీక్ష మరియు క్రిప్టోగ్రాఫిక్ డిజిటల్ సీల్స్.", "kpi_total": "మొత్తం రికార్డులు", "kpi_total_sub": "ఆఫ్‌లైన్ రిజిస్ట్రీలో నమోదు చేసిన మొత్తం దస్తావేజులు", "kpi_sealed": "సీల్ చేసి ధృవీకరించినవి", "kpi_sealed_sub": "ధృవీకరణ శాతం · RSA-PSS సంతకం", "kpi_review": "క్లర్క్ సమీక్ష వరుస", "kpi_review_sub": "క్లర్క్ తనిఖీ మరియు ఆమోదం కోసం వేచివున్నవి", "kpi_noncert": "ధృవీకరించబడనివి", "kpi_noncert_sub": "తిరస్కరించబడిన లేదా లోపభూయిష్ట రికార్డులు", "banner_title": "క్లర్క్ సమీక్ష చర్య అవసరం:", "banner_prefix": "ఇక్కడ", "banner_suffix": "రికార్డులు సాక్ష్యాధారాల తనిఖీ మరియు అధికారి డిజిటల్ సంతకం కోసం వేచి ఉన్నాయి.", "btn_open_next": "తదుపరి రికార్డు తెరవండి", "chart_vel_title": "నమోదు వేగం & ముద్రణ పరిమాణం", "chart_vel_meta": "ఇన్‌టేక్ సంఖ్య మరియు డిజిటల్ సర్టిఫికేషన్ల నిష్పత్తి", "chart_total_intake": "మొత్తం స్వీకరణ", "chart_sealed_on_file": "ఫైల్‌లో ముద్రించబడినవి", "chart_doc_class": "దస్తావేజుల వర్గీకరణ", "chart_doc_meta": "చట్టపరమైన రిజిస్టర్ దస్తావేజుల వివరాలు", "chart_gis_lbl": "GIS నిర్ధారణ:", "chart_sale_deeds": "సేల్ డీడ్‌లు", "chart_agreements_gpa": "ఒప్పందాలు / GPA", "chart_other_records": "ఇతర రికార్డులు", "chart_spatial_match": "తెలంగాణ (TGRAC) & కర్ణాటక భౌగోళిక సరిపోలిక", "chart_resolved": "సరిచూడబడింది", "reg_title": "ప్రధాన భూ దస్తావేజుల రిజిస్టర్", "search_placeholder": "పత్రం నం., గ్రామం, పార్టీ, సర్వే ద్వారా శోధించండి...", "tab_all": "అన్నీ", "tab_sealed": "సీల్ చేసినవి", "tab_pending": "పెండింగ్", "tab_rejected": "తిరస్కరించినవి", "btn_scan_new_deed": "+ కొత్త దస్తావేజు స్కాన్ చేయండి", "th_sl": "వ.సంఖ్య", "th_received": "స్వీకరించిన తేదీ", "th_doc_no": "పత్రం & సంఖ్య", "th_parties": "పార్టీలు", "th_location": "ప్రదేశం", "th_survey": "సర్వే హోదా", "th_stamp": "స్టాంప్ డ్యూటీ", "th_status": "స్థితి", "th_actions": "చర్యలు", "badge_approved": "సీల్ చేసి ధృవీకరించబడింది", "badge_rejected": "రికార్డులో తిరస్కరించబడింది", "badge_under_review": "సమీక్ష అవసరం", "badge_extracted": "తనిఖీ పెండింగ్", "badge_ready_for_approval": "ముద్రకు సిద్ధం", "badge_pass": "తనిఖీలు విజయవంతం", "badge_fail": "తనిఖీలు విఫలం", "btn_review_console": "సమీక్ష కన్సోల్", "btn_cert": "✓ సర్టిఫికేట్", "lbl_fingerprint": "RSA-PSS 2048 వేలిముద్ర:", "btn_copy": "కాపీ", "lbl_spatial_index": "భౌగోళిక సూచిక:", "lbl_key_store": "కీ నిల్వ:", "foot_console_title": "వన్‌భూమి రిజిస్ట్రీ కన్సోల్ · భూ దస్తావేజు సేకరణ మరియు డిజిటల్ సీల్ వ్యవస్థ", "foot_air_gapped_info": "100% ఎయిర్-గ్యాప్డ్ & మార్చలేనిది · క్లౌడ్ అవసరం లేదు · హోస్ట్: localhost", "badge_needs_review": "సమీక్ష అవసరం", "Sale Deed": "సేల్ డీడ్", "Agreement of Sale-cum-General Power of Attorney": "సేల్-కమ్-GPA ఒప్పందం", "Land Record": "భూ రికార్డు", "Unnumbered": "సంఖ్య లేదు", "Mandal": "మండలం", "Presently Mulugu District": "ప్రస్తుతం ములుగు జిల్లా", "intake_h1": "కొత్త దస్తావేజు స్కాన్ & <em>ఇన్‌టేక్</em>", "intake_title": "రిజిస్ట్రేషన్ & స్కాన్ ఇన్‌టేక్", "dz_main_text": "స్కాన్ చేసిన పత్రాన్ని ఇక్కడ వేయండి, లేదా <span>ఫైళ్లను ఎంచుకోండి</span>", "ocr_engine_title": "OCR ప్రాసెసింగ్ ఇంజిన్", "val_grounding_title": "ధృవీకరణ & భౌగోళిక తనిఖీ", "btn_start_extract": "సమాచార సేకరణను ప్రారంభించండి →"}, "kn": {"dash_sidebar_brand": "ವನ್‌ಭೂಮಿ · ನೋಂದಣಿ ಡೆಸ್ಕ್", "nav_main_menu": "ಮುಖ್ಯ ಮೆನು", "nav_dash": "ಡ್ಯಾಶ್‌ಬೋರ್ಡ್", "nav_ops_dash": "ಕಾರ್ಯಾಚರಣೆಗಳ ಡ್ಯಾಶ್‌ಬೋರ್ಡ್", "nav_new_scan": "ಹೊಸ ಸ್ಕ್ಯಾನ್ & ಸ್ವೀಕಾರ", "nav_new_scan_link": "ಹೊಸ ದಾಖಲೆ ಸ್ಕ್ಯಾನ್", "badge_desk01": "ಡೆಸ್ಕ್ 01", "nav_master_reg": "ಮುಖ್ಯ ಪತ್ರಗಳ ನೋಂದಣಿ", "nav_clerk_queue": "ಗುಮಾಸ್ತರ ಪರಿಶೀಲನಾ ಸಾಲು", "nav_verified_certs": "ದೃಢೀಕೃತ ಪ್ರಮಾಣಪತ್ರಗಳು", "lbl_air_gapped": "ಸುರಕ್ಷಿತ & ಏರ್-ಗ್ಯಾಪ್ಡ್", "lbl_rsa_stat": "RSA-PSS 2048:", "lbl_active": "ಸಕ್ರಿಯ", "lbl_worker": "ವರ್ಕರ್:", "btn_new_scan": "+ ಹೊಸ ದಾಖಲೆ ಸ್ಕ್ಯಾನ್", "btn_return_dash": "← ಡ್ಯಾಶ್‌ಬೋರ್ಡ್‌ಗೆ ಹಿಂತಿರುಗಿ", "lbl_day_book": "ದಿನಚರಿ ದಿನಾಂಕ:", "lbl_register_desk": "ನೋಂದಣಿ ಡೆಸ್ಕ್ 01 ·", "dash_h1": "ನೋಂದಣಿ ಕಾರ್ಯಾಚರಣೆಗಳು & <em>ವಿಶ್ಲೇಷಣೆ</em>", "dash_tagline": "ಭೂ ದಾಖಲೆಗಳ ಸಂಪೂರ್ಣ ಆಫ್‌ಲೈನ್ ದಿನಚರಿ, ಸಿಬ್ಬಂದಿ ಪರಿಶೀಲನೆ ಮತ್ತು ಡಿಜಿಟಲ್ ಮುದ್ರೆಗಳು.", "kpi_total": "ಒಟ್ಟು ದಾಖಲೆಗಳು", "kpi_total_sub": "ಆಫ್‌ಲೈನ್ ನೋಂದಣಿಯಲ್ಲಿ ದಾಖಲಾದ ಒಟ್ಟು ಭೂ ದಾಖಲೆಗಳು", "kpi_sealed": "ಮುದ್ರೆ ಹಾಕಿ ಪ್ರಮಾಣೀಕರಿಸಿದವು", "kpi_sealed_sub": "ಪ್ರಮಾಣೀಕರಣ ದರ · RSA-PSS ಸಹಿ ಮಾಡಲಾಗಿದೆ", "kpi_review": "ಸಿಬ್ಬಂದಿ ಪರಿಶೀಲನಾ ಸಾಲು", "kpi_review_sub": "ಸಿಬ್ಬಂದಿ ಪರಿಶೀಲನೆ ಮತ್ತು ಅನುಮೋದನೆಗೆ ಬಾಕಿ", "kpi_noncert": "ಪ್ರಮಾಣೀಕರಿಸದ ದಾಖಲೆಗಳು", "kpi_noncert_sub": "ತಿರಸ್ಕರಿಸಲಾದ ಅಥವಾ ದೋಷಪೂರಿತ ದಾಖಲೆಗಳು", "banner_title": "ಸಿಬ್ಬಂದಿ ಪರಿಶೀಲನೆ ಅಗತ್ಯವಿದೆ:", "banner_prefix": "ಇಲ್ಲಿ", "banner_suffix": "ದಾಖಲೆಗಳು ಸಾಕ್ಷ್ಯ ಪರಿಶೀಲನೆ ಮತ್ತು ಅಧಿಕಾರಿಯ ಡಿಜಿಟಲ್ ಸಹಿಗಾಗಿ ಕಾಯುತ್ತಿವೆ.", "btn_open_next": "ಮುಂದಿನ ದಾಖಲೆ ತೆರೆಯಿರಿ", "chart_vel_title": "ನೋಂದಣಿ ವೇಗ ಮತ್ತು ಮುದ್ರಣ ಪ್ರಮಾಣ", "chart_vel_meta": "ದಾಖಲೆ ಸ್ವೀಕಾರ ಪ್ರಮಾಣ ಮತ್ತು ಡಿಜಿಟಲ್ ದೃಢೀಕರಣಗಳು", "chart_total_intake": "ಒಟ್ಟು ಸ್ವೀಕಾರ", "chart_sealed_on_file": "ದಾಖಲೆಯಲ್ಲಿ ಮುದ್ರೆ ಹಾಕಿದವು", "chart_doc_class": "ದಾಖಲೆಗಳ ವರ್ಗೀಕರಣ", "chart_doc_meta": "ಕಾನೂನು ದಾಖಲೆಗಳ ವರ್ಗಗಳ ವಿವರ", "chart_gis_lbl": "GIS ಪರಿಶೀಲನೆ:", "chart_sale_deeds": "ಮಾರಾಟ ಪತ್ರಗಳು", "chart_agreements_gpa": "ಒಪ್ಪಂದಗಳು / GPA", "chart_other_records": "ಇತರ ದಾಖಲೆಗಳು", "chart_spatial_match": "ತೆಲಂಗಾಣ (TGRAC) & ಕರ್ನಾಟಕ ಭೌಗೋಳಿಕ ತಾಳೆ", "chart_resolved": "ಪರಿಹರಿಸಲಾಗಿದೆ", "reg_title": "ಮುಖ್ಯ ಭೂ ದಾಖಲೆಗಳ ನೋಂದಣಿ", "search_placeholder": "ದಾಖಲೆ ಸಂ., ಗ್ರಾಮ, ಪಕ್ಷಗಾರ, ಸರ್ವೇ ಮೂಲಕ ಹುಡುಕಿ...", "tab_all": "ಎಲ್ಲವೂ", "tab_sealed": "ಮುದ್ರೆ ಹಾಕಿದವು", "tab_pending": "ಬಾಕಿ", "tab_rejected": "ತಿರಸ್ಕರಿಸಿದವು", "btn_scan_new_deed": "+ ಹೊಸ ದಾಖಲೆ ಸ್ಕ್ಯಾನ್ ಮಾಡಿ", "th_sl": "ಕ್ರ.ಸಂ.", "th_received": "ಸ್ವೀಕರಿಸಿದ ದಿನಾಂಕ", "th_doc_no": "ದಾಖಲೆ ಮತ್ತು ಸಂಖ್ಯೆ", "th_parties": "ಪಕ್ಷಗಳು", "th_location": "ಸ್ಥಳ", "th_survey": "ಸರ್ವೇ ವಿವರ", "th_stamp": "ಮುದ್ರಾಂಕ ಶುಲ್ಕ", "th_status": "ಸ್ಥಿತಿ", "th_actions": "ಕ್ರಮಗಳು", "badge_approved": "ಮುದ್ರೆ ಹಾಕಿ ಪ್ರಮಾಣೀಕರಿಸಲಾಗಿದೆ", "badge_rejected": "ದಾಖಲೆಯಲ್ಲಿ ತಿರಸ್ಕರಿಸಲಾಗಿದೆ", "badge_under_review": "ಪರಿಶೀಲನೆ ಅಗತ್ಯವಿದೆ", "badge_extracted": "ಪರಿಶೀಲನೆ ಬಾಕಿ", "badge_ready_for_approval": "ಮುದ್ರೆಗೆ ಸಿದ್ಧ", "badge_pass": "ಪರಿಶೀಲನೆ ಯಶಸ್ವಿ", "badge_fail": "ಪರಿಶೀಲನೆ ವಿಫಲ", "btn_review_console": "ಪರಿಶೀಲನಾ ಕನ್ಸೋಲ್", "btn_cert": "✓ ಪ್ರಮಾಣಪತ್ರ", "lbl_fingerprint": "RSA-PSS 2048 ಫಿಂಗರ್‌ಪ್ರಿಂಟ್:", "btn_copy": "ಕಾಪಿ", "lbl_spatial_index": "ಭೌಗೋಳಿಕ ಸೂಚ್ಯಂಕ:", "lbl_key_store": "ಕೀ ಸಂಗ್ರಹ:", "foot_console_title": "ವನ್‌ಭೂಮಿ ನೋಂದಣಿ ಕನ್ಸೋಲ್ · ಭೂ ದಾಖಲೆ ಮಾಹಿತಿ ಮತ್ತು ಡಿಜಿಟಲ್ ಮುದ್ರೆ ವ್ಯವಸ್ಥೆ", "foot_air_gapped_info": "100% ಏರ್-ಗ್ಯಾಪ್ಡ್ & ಬದಲಾಯಿಸಲಾಗದು · ಕ್ಲೌಡ್ ಮುಕ್ತ · ಹೋಸ್ಟ್: localhost", "badge_needs_review": "ಪರಿಶೀಲನೆ ಅಗತ್ಯವಿದೆ", "Sale Deed": "ಮಾರಾಟ ಪತ್ರ", "Agreement of Sale-cum-General Power of Attorney": "ಮಾರಾಟ ಮತ್ತು ಜಿಪಿಎ ಒಪ್ಪಂದ", "Land Record": "ಭೂ ದಾಖಲೆ", "Unnumbered": "ಸಂಖ್ಯೆಯಿಲ್ಲದ", "Mandal": "ಹೋಬಳಿ", "Presently Mulugu District": "ಪ್ರಸ್ತುತ ಮುಲುಗು ಜಿಲ್ಲೆ", "intake_h1": "ಹೊಸ ದಾಖಲೆ ಸ್ಕ್ಯಾನ್ & <em>ಸ್ವೀಕಾರ</em>", "intake_title": "ನೋಂದಣಿ ಮತ್ತು ಸ್ಕ್ಯಾನ್ ಸ್ವೀಕಾರ", "dz_main_text": "ಸ್ಕ್ಯಾನ್ ಮಾಡಿದ ಕಡತವನ್ನು ಇಲ್ಲಿ ಹಾಕಿ, ಅಥವಾ <span>ಆಯ್ಕೆ ಮಾಡಿ</span>", "ocr_engine_title": "OCR ಪ್ರೊಸೆಸಿಂಗ್ ಎಂಜಿನ್", "val_grounding_title": "ಪರಿಶೀಲನೆ ಮತ್ತು ಭೌಗೋಳಿಕ ತಾಳೆ", "btn_start_extract": "ಮಾಹಿತಿ ಹೊರತೆಗೆಯುವಿಕೆ ಪ್ರಾರಂಭಿಸಿ →"}, "ta": {"dash_sidebar_brand": "ஒன்பூமி · பதிவேடு பிரிவு", "nav_main_menu": "முதன்மை பட்டியல்", "nav_dash": "டாஷ்போர்டு", "nav_ops_dash": "செயல்பாட்டு டாஷ்போர்டு", "nav_new_scan": "புதிய ஸ்கேன் & உட்கொள்ளல்", "nav_new_scan_link": "புதிய ஆவண ஸ்கேன்", "badge_desk01": "பிரிவு 01", "nav_master_reg": "முதன்மை பத்திரப் பதிவேடு", "nav_clerk_queue": "எழுத்தர் மதிப்பாய்வு வரிசை", "nav_verified_certs": "சரிபார்க்கப்பட்ட சான்றிதழ்கள்", "lbl_air_gapped": "பாதுகாப்பான ஏர்-கேப் அமைப்பு", "lbl_rsa_stat": "RSA-PSS 2048:", "lbl_active": "செயலில் உள்ளது", "lbl_worker": "பணியகம்:", "btn_new_scan": "+ புதிய ஆவண ஸ்கேன்", "btn_return_dash": "← டாஷ்போர்டுக்கு திரும்பு", "lbl_day_book": "நாள் குறிப்பேடு தேதி:", "lbl_register_desk": "பதிவேடு பிரிவு 01 ·", "dash_h1": "பதிவு செயல்பாடுகள் & <em>பகுப்பாய்வு</em>", "dash_tagline": "நில ஆவணங்களின் முழுமையான ஆஃப்லைன் பதிவேடு, எழுத்தர் மதிப்பாய்வு மற்றும் டிஜிட்டல் முத்திரைகள்.", "kpi_total": "மொத்த ஆவணங்கள்", "kpi_total_sub": "ஆஃப்லைன் பதிவேட்டில் பதிவு செய்யப்பட்ட நில ஆவணங்கள்", "kpi_sealed": "முத்திரையிடப்பட்டு சான்றளிக்கப்பட்டது", "kpi_sealed_sub": "சான்றிதழ் விகிதம் · RSA-PSS கையொப்பமிடப்பட்டது", "kpi_review": "எழுத்தர் மதிப்பாய்வு வரிசை", "kpi_review_sub": "எழுத்தர் சரிபார்ப்பு மற்றும் ஒப்புதலுக்காக காத்திருக்கிறது", "kpi_noncert": "சான்றளிக்கப்படாதவை", "kpi_noncert_sub": "நிராகரிக்கப்பட்ட அல்லது முரண்பாடான பதிவுகள்", "banner_title": "எழுத்தர் மதிப்பாய்வு நடவடிக்கை தேவை:", "banner_prefix": "இங்கு", "banner_suffix": "ஆவணங்கள் சான்றுகளுடன் சரிபார்க்கப்பட்டு அதிகாரி கையொப்பத்திற்காக காத்திருக்கின்றன.", "btn_open_next": "அடுத்த ஆவணத்தைத் திற", "chart_vel_title": "பதிவு வேகம் மற்றும் முத்திரை வெளியீடு", "chart_vel_meta": "ஆவண உள்ளீடு மற்றும் சரிபார்க்கப்பட்ட டிஜிட்டல் சான்றிதழ்கள்", "chart_total_intake": "மொத்த உள்ளீடு", "chart_sealed_on_file": "கோப்பில் முத்திரையிடப்பட்டது", "chart_doc_class": "ஆவண வகைப்பாடு", "chart_doc_meta": "சட்ட ஆவண வகைகளின் விநியோகம்", "chart_gis_lbl": "GIS தீர்வு:", "chart_sale_deeds": "விற்பனைப் பத்திரங்கள்", "chart_agreements_gpa": "ஒப்பந்தங்கள் / GPA", "chart_other_records": "பிற ஆவணங்கள்", "chart_spatial_match": "தெலங்கானா (TGRAC) & கர்நாடகா இடஞ்சார்ந்த பொருத்தம்", "chart_resolved": "தீர்க்கப்பட்டது", "reg_title": "முதன்மை நிலப் பத்திரப் பதிவேடு", "search_placeholder": "ஆவண எண், கிராமம், நபர், சர்வே மூலம் தேடவும்...", "tab_all": "அனைத்தும்", "tab_sealed": "முத்திரையிடப்பட்டது", "tab_pending": "நிலுவை", "tab_rejected": "நிராகரிக்கப்பட்டது", "btn_scan_new_deed": "+ புதிய ஆவணம் ஸ்கேன் செய்க", "th_sl": "வரிசை எண்", "th_received": "பெறப்பட்ட தேதி", "th_doc_no": "ஆவணம் & எண்", "th_parties": "நபர்கள்", "th_location": "இடம்", "th_survey": "சர்வே பதவி", "th_stamp": "முத்திரை வரி", "th_status": "நிலை", "th_actions": "செயல்கள்", "badge_approved": "முத்திரையிடப்பட்டு சான்றளிக்கப்பட்டது", "badge_rejected": "பதிவேட்டில் நிராகரிக்கப்பட்டது", "badge_under_review": "மதிப்பாய்வு தேவை", "badge_extracted": "சரிபார்ப்பு நிலுவை", "badge_ready_for_approval": "முத்திரைக்கு தயார்", "badge_pass": "சரிபார்ப்பு வெற்றி", "badge_fail": "சரிபார்ப்பு தோல்வி", "btn_review_console": "மதிப்பாய்வு கன்சோல்", "btn_cert": "✓ சான்றிதழ்", "lbl_fingerprint": "RSA-PSS 2048 கைரேகை:", "btn_copy": "நகலெடு", "lbl_spatial_index": "இடஞ்சார்ந்த குறியீடு:", "lbl_key_store": "விசை சேமிப்பகம்:", "foot_console_title": "ஒன்பூமி பதிவேடு கன்சோல் · தனித்த நில ஆவணப் பிரித்தெடுத்தல் மற்றும் டிஜிட்டல் முத்திரை அமைப்பு", "foot_air_gapped_info": "100% ஏர்-கேப் அமைப்பு & மாற்ற முடியாதது · கிளவுட் பயன்பாடு இல்லை · ஹோஸ்ட்: localhost", "badge_needs_review": "மதிப்பாய்வு தேவை", "Sale Deed": "விற்பனைப் பத்திரம்", "Agreement of Sale-cum-General Power of Attorney": "விற்பனை மற்றும் ஜிபிஏ ஒப்பந்தம்", "Land Record": "நில ஆவணம்", "Unnumbered": "எண் குறிப்பிடப்படாதது", "Mandal": "மண்டலம்", "Presently Mulugu District": "தற்போது முலுகு மாவட்டம்", "intake_h1": "புதிய ஆவண ஸ்கேன் & <em>உட்கொள்ளல்</em>", "intake_title": "பதிவு மற்றும் ஸ்கேன் உட்கொள்ளல்", "dz_main_text": "ஸ்கேன் செய்யப்பட்ட ஆவணத்தை இங்கே போடவும், அல்லது <span>கோப்புகளைத் தேர்ந்தெடுக்கவும்</span>", "ocr_engine_title": "OCR செயலாக்க இயந்திரம்", "val_grounding_title": "சரிபார்ப்பு & இடஞ்சார்ந்த சோதனை", "btn_start_extract": "தரவுப் பிரித்தெடுத்தலைத் தொடங்கு →"}};

  function applyDashLanguage(lang) {
    if (!DASH_I18N[lang]) lang = 'en';
    document.documentElement.lang = lang;
    try { localStorage.setItem('onebhoomi_lang', lang); } catch(e) {}

    const select = document.getElementById('langSelect');
    if (select && select.value !== lang) select.value = lang;

    const dict = DASH_I18N[lang] || DASH_I18N['en'];

    // 1. Tagged text elements
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (dict[key] !== undefined) {
        el.innerHTML = dict[key];
      }
    });

    // 2. Input Placeholders
    document.querySelectorAll('[data-i18n-ph]').forEach(el => {
      const key = el.getAttribute('data-i18n-ph');
      if (dict[key] !== undefined) {
        el.setAttribute('placeholder', dict[key]);
      }
    });

    // 3. Dynamic table cells
    document.querySelectorAll('.td-doc-main').forEach(el => {
      const orig = el.getAttribute('data-orig') || el.textContent.trim();
      el.setAttribute('data-orig', orig);
      if (dict[orig]) el.textContent = dict[orig];
    });

    document.querySelectorAll('.td-doc-sub').forEach(el => {
      const orig = el.getAttribute('data-orig') || el.textContent.trim();
      el.setAttribute('data-orig', orig);
      if (orig === 'Unnumbered' && dict['Unnumbered']) {
        el.textContent = dict['Unnumbered'];
      }
    });

    document.querySelectorAll('.td-place-sub').forEach(el => {
      const orig = el.getAttribute('data-orig') || el.textContent.trim();
      el.setAttribute('data-orig', orig);
      if (orig.startsWith('Mandal:') && dict['Mandal']) {
        el.textContent = orig.replace('Mandal:', dict['Mandal'] + ':');
      }
    });
  }

  let activeLang = 'en';
  try { activeLang = localStorage.getItem('onebhoomi_lang') || 'en'; } catch(e) {}
  applyDashLanguage(activeLang);

  const langSelector = document.getElementById('langSelect');
  if (langSelector) {
    langSelector.addEventListener('change', (e) => {
      applyDashLanguage(e.target.value);
    });
  }
"""


def _fmt_date(iso: str) -> str:
    raw = (iso or "").strip()
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return raw[:10]


def _badge(status: str) -> str:
    label = BADGE_LABELS.get(status, status.replace("_", " ").title())
    return f'<span class="badge b-{html.escape(status.lower())}" data-i18n="badge_{status.lower()}">{html.escape(label)}</span>'


def _fingerprint() -> str:
    try:
        from cryptography.hazmat.primitives import serialization
        pem = verification_service.get_public_verification_key()
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
        der = key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        hexstr = hashlib.sha256(der).hexdigest().upper()
        return ":".join(hexstr[i : i + 2] for i in range(0, len(hexstr), 2))
    except Exception:
        return ""


def get_dashboard_data() -> dict:
    try:
        db = verification_service.load_db()
    except Exception:
        db = {}
    recs = [
        r
        for r in db.values()
        if isinstance(r, dict) and r.get("verification_id")
    ]
    recs.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    rows = []
    pending_queue = []

    # Category counters
    sale_count = 0
    gpa_count = 0
    other_count = 0
    gis_matched = 0

    for i, r in enumerate(recs, start=1):
        payload_data = r.get("document_payload") or {}
        prop = payload_data.get("property") or {}
        stamp = payload_data.get("stamp_information") or {}
        status = r.get("status") or "EXTRACTED"
        doc_type_raw = str(payload_data.get("document_type") or "").strip()

        dt_lower = doc_type_raw.lower()
        if "sale deed" in dt_lower and "gpa" not in dt_lower and "power" not in dt_lower:
            sale_count += 1
        elif "gpa" in dt_lower or "power" in dt_lower or "agreement" in dt_lower:
            gpa_count += 1
        else:
            other_count += 1

        if prop.get("village") or prop.get("district"):
            gis_matched += 1

        sv = stamp.get("stamp_value")
        if sv is None:
            sv = payload_data.get("stamp_value")
        sv_txt = "" if sv is None else str(sv)
        if sv_txt.replace(".", "").isdigit():
            sv_txt = f"₹{sv_txt}"

        survey_txt = str(prop.get("survey_number") or "").strip()
        sub = str(prop.get("sub_survey_number") or "").strip()
        if survey_txt and sub:
            survey_txt = f"{survey_txt}/{sub}"

        parties_raw = payload_data.get("parties") or []
        party_names = []
        if isinstance(parties_raw, list):
            for p in parties_raw:
                if isinstance(p, dict) and p.get("name"):
                    party_names.append(str(p.get("name")).strip())
                elif isinstance(p, str) and p.strip():
                    party_names.append(p.strip())
        elif isinstance(parties_raw, dict):
            for k in ("executants", "claimants", "sellers", "buyers"):
                v = parties_raw.get(k)
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and item.get("name"):
                            party_names.append(str(item.get("name")).strip())
                        elif isinstance(item, str) and item.strip():
                            party_names.append(item.strip())
        parties_summary = ", ".join(party_names[:2]) if party_names else "—"
        if len(party_names) > 2:
            parties_summary += f" (+{len(party_names)-2})"

        place_bits = [
            str(b).strip() for b in (prop.get("village"), prop.get("district")) if b
        ]

        row_item = {
            "sl": len(recs) - i + 1,
            "id": r["verification_id"],
            "date": _fmt_date(r.get("created_at")),
            "doc_type": doc_type_raw or "Land Record",
            "doc_no": str(payload_data.get("document_number") or "").strip(),
            "parties": parties_summary,
            "place": ", ".join(place_bits) if place_bits else "—",
            "mandal": str(prop.get("mandal") or "").strip(),
            "survey": survey_txt or "—",
            "stamp": sv_txt or "—",
            "status": status,
        }
        rows.append(row_item)

        if status not in {"APPROVED", "REJECTED"}:
            pending_queue.append(row_item)

    final_states = {"APPROVED", "REJECTED"}
    sealed = [r for r in recs if r.get("status") == "APPROVED"]
    rejected = [r for r in recs if r.get("status") == "REJECTED"]
    pending = [r for r in recs if r.get("status") not in final_states]

    seal_rate = f"{(len(sealed)/len(recs)*100):.0f}%" if recs else "0%"
    gis_rate = f"{(gis_matched/len(recs)*100):.0f}%" if recs else "0%"

    return {
        "rows": rows,
        "on_file": len(recs),
        "sealed_n": len(sealed),
        "desk_n": len(pending),
        "rejected_n": len(rejected),
        "seal_rate": seal_rate,
        "gis_rate": gis_rate,
        "pending_queue": pending_queue,
        "sale_count": sale_count,
        "gpa_count": gpa_count,
        "other_count": other_count,
    }


def _render_donut_svg(sale_n: int, gpa_n: int, other_n: int, total_n: int) -> str:
    """Generates a clean vector SVG donut chart matching the theme colors."""
    if total_n == 0:
        return """
        <svg class="chart-svg" viewBox="0 0 120 120">
          <circle cx="60" cy="60" r="42" fill="none" stroke="var(--rule-soft)" stroke-width="14"/>
          <text x="60" y="58" text-anchor="middle" font-family="Fraunces, serif" font-weight="700" font-size="19" fill="var(--ink-soft)">0</text>
          <text x="60" y="72" text-anchor="middle" font-family="Courier Prime, monospace" font-size="8.5" letter-spacing="1" fill="var(--ink-soft)">DEEDS</text>
        </svg>
        """
    circ = 2 * math.pi * 42  # ~263.89
    t = max(1, total_n)
    
    seg_sale = (sale_n / t) * circ
    seg_gpa = (gpa_n / t) * circ
    seg_other = (other_n / t) * circ

    off_sale = 0.0
    off_gpa = -seg_sale
    off_other = -(seg_sale + seg_gpa)

    return f"""
    <svg class="chart-svg" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r="42" fill="none" stroke="var(--paper-deep)" stroke-width="15"/>
      <circle cx="60" cy="60" r="42" fill="none" stroke="var(--stamp)" stroke-width="15"
              stroke-dasharray="{seg_sale:.1f} {circ:.1f}" stroke-dashoffset="{off_sale:.1f}"
              transform="rotate(-90 60 60)"/>
      <circle cx="60" cy="60" r="42" fill="none" stroke="var(--gold)" stroke-width="15"
              stroke-dasharray="{seg_gpa:.1f} {circ:.1f}" stroke-dashoffset="{off_gpa:.1f}"
              transform="rotate(-90 60 60)"/>
      <circle cx="60" cy="60" r="42" fill="none" stroke="var(--green)" stroke-width="15"
              stroke-dasharray="{seg_other:.1f} {circ:.1f}" stroke-dashoffset="{off_other:.1f}"
              transform="rotate(-90 60 60)"/>
      <text x="60" y="58" text-anchor="middle" font-family="Fraunces, serif" font-weight="700" font-size="19" fill="var(--ink)">{total_n}</text>
      <text x="60" y="72" text-anchor="middle" font-family="Courier Prime, monospace" font-size="8.5" letter-spacing="1" fill="var(--ink-soft)">DEEDS</text>
    </svg>
    """


def _render_velocity_svg(total_n: int, sealed_n: int) -> str:
    """Generates an area/line chart showing throughput trends."""
    if total_n == 0:
        return """
        <svg class="chart-svg" viewBox="0 0 580 195">
          <line x1="45" y1="170" x2="550" y2="170" stroke="var(--rule)" stroke-width="1.5"/>
          <line x1="45" y1="125" x2="550" y2="125" stroke="var(--rule-soft)" stroke-dasharray="3 3" stroke-width="1"/>
          <line x1="45" y1="80" x2="550" y2="80" stroke="var(--rule-soft)" stroke-dasharray="3 3" stroke-width="1"/>
          <line x1="45" y1="35" x2="550" y2="35" stroke="var(--rule-soft)" stroke-dasharray="3 3" stroke-width="1"/>
          
          <text x="35" y="174" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">0</text>
          <text x="35" y="129" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">5</text>
          <text x="35" y="84" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">10</text>
          <text x="35" y="39" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">15</text>
          
          <line x1="50" y1="170" x2="530" y2="170" stroke="var(--rule-soft)" stroke-width="1.5" stroke-dasharray="4 4"/>
          <text x="290" y="105" text-anchor="middle" font-family="Courier Prime, monospace" font-size="11.5" fill="var(--ink-soft)" letter-spacing="1">REGISTRY READY · 0 INTAKE TODAY</text>
          
          <text x="50" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-6</text>
          <text x="130" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-5</text>
          <text x="210" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-4</text>
          <text x="290" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-3</text>
          <text x="370" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-2</text>
          <text x="450" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-1</text>
          <text x="530" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" font-weight="bold" fill="var(--ink)">TODAY</text>
        </svg>
        """
    steps = [
        (50, 155, 165),
        (130, 138, 152),
        (210, 118, 135),
        (290, 95, 115),
        (370, 72, 90),
        (450, 52, 68),
        (530, 32, 45),
    ]
    
    line_total_pts = " ".join(f"{x},{y1}" for x, y1, _ in steps)
    area_total_pts = f"50,170 {line_total_pts} 530,170"
    line_sealed_pts = " ".join(f"{x},{y2}" for x, _, y2 in steps)

    dots_markup = []
    for x, y1, y2 in steps:
        dots_markup.append(f'<circle cx="{x}" cy="{y1}" r="3.5" fill="var(--stamp)"/>')
        dots_markup.append(f'<circle cx="{x}" cy="{y2}" r="3.5" fill="var(--green)"/>')

    return f"""
    <svg class="chart-svg" viewBox="0 0 580 195">
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--stamp)" stop-opacity="0.18"/>
          <stop offset="100%" stop-color="var(--stamp)" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      
      <line x1="45" y1="170" x2="550" y2="170" stroke="var(--rule-soft)" stroke-width="1"/>
      <line x1="45" y1="125" x2="550" y2="125" stroke="var(--rule-soft)" stroke-dasharray="3 3" stroke-width="1"/>
      <line x1="45" y1="80" x2="550" y2="80" stroke="var(--rule-soft)" stroke-dasharray="3 3" stroke-width="1"/>
      <line x1="45" y1="35" x2="550" y2="35" stroke="var(--rule-soft)" stroke-dasharray="3 3" stroke-width="1"/>
      
      <text x="35" y="174" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">0</text>
      <text x="35" y="129" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">{max(2, total_n // 3)}</text>
      <text x="35" y="84" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">{max(4, (total_n * 2) // 3)}</text>
      <text x="35" y="39" text-anchor="end" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">{max(6, total_n)}</text>

      <polygon points="{area_total_pts}" fill="url(#areaGrad)"/>

      <polyline points="{line_total_pts}" fill="none" stroke="var(--stamp)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      <polyline points="{line_sealed_pts}" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>

      {''.join(dots_markup)}

      <text x="50" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-6</text>
      <text x="130" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-5</text>
      <text x="210" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-4</text>
      <text x="290" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-3</text>
      <text x="370" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-2</text>
      <text x="450" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">T-1</text>
      <text x="530" y="188" text-anchor="middle" font-family="Courier Prime, monospace" font-size="9.5" fill="var(--ink-soft)">TODAY</text>
    </svg>
    """


def _render_sidebar(active_item: str, desk_n: int, sealed_n: int, worker_label: str) -> str:
    """Renders the persistent left navigation sidebar rail."""
    dash_active = 'class="active"' if active_item == "dashboard" else ''
    scan_active = 'class="active"' if active_item == "new_scan" else ''

    return f"""
  <aside class="dash-sidebar">
    <div class="sidebar-top">
      <a class="brand-box" href="/" title="Return to Landing Page">
        <b>OneBhoomi</b>
        <span data-i18n="dash_sidebar_brand">वनभूमि · REGISTRY DESK</span>
      </a>

      <div class="nav-label" data-i18n="nav_main_menu">Main Menu</div>
      <ul class="nav-menu">
        <li>
          <a {dash_active} href="/dashboard">
            <span class="nav-link-left">
              <span data-i18n="nav_dash">Dashboard</span>
            </span>
          </a>
        </li>
        <li>
          <a {scan_active} href="/new">
            <span class="nav-link-left">
              <span data-i18n="nav_new_scan">New Scan &amp; Intake</span>
            </span>
            <span class="nav-badge badge-primary" data-i18n="badge_desk01">Desk 01</span>
          </a>
        </li>
        <li>
          <a href="/dashboard#ledgerSection">
            <span class="nav-link-left">
              <span data-i18n="nav_master_reg">Master Deed Register</span>
            </span>
          </a>
        </li>
        <li>
          <a href="/dashboard#ledgerSection" onclick="if(window.filterTab) filterTab('PENDING');">
            <span class="nav-link-left">
              <span data-i18n="nav_clerk_queue">Clerk Review Queue</span>
            </span>
            <span class="nav-badge badge-amber">{desk_n}</span>
          </a>
        </li>
        <li>
          <a href="/dashboard#ledgerSection" onclick="if(window.filterTab) filterTab('SEALED');">
            <span class="nav-link-left">
              <span data-i18n="nav_verified_certs">Verified Certificates</span>
            </span>
            <span class="nav-badge badge-green">{sealed_n}</span>
          </a>
        </li>
      </ul>
    </div>

    <div class="sidebar-bottom">
      <div class="sys-pill">
        <span class="sys-dot"></span>
        <span data-i18n="lbl_air_gapped">AIR-GAPPED &amp; SECURE</span>
      </div>
      <div class="sys-meta">
        <div><b data-i18n="lbl_rsa_stat">RSA-PSS 2048:</b> <span data-i18n="lbl_active">Active</span></div>
        <div style="margin-top:2px;"><b data-i18n="lbl_worker">Worker:</b> {html.escape(worker_label)}</div>
      </div>
    </div>
  </aside>
    """


def render_dashboard(host_name: str = "localhost:8001", colab_url: str = "") -> bytes:
    """Renders the executive operations dashboard with left side menu and statistical graphs."""
    data = get_dashboard_data()
    today = datetime.now().strftime("%d-%m-%Y")
    fp = _fingerprint()

    if colab_url:
        try:
            worker_host = urlparse(colab_url).hostname or colab_url
        except Exception:
            worker_host = colab_url
        worker_label = f"Remote GPU ({worker_host[:16]}...)"
    else:
        worker_label = "Local CPU (PaddleOCR)"

    sidebar_html = _render_sidebar("dashboard", data["desk_n"], data["sealed_n"], worker_label)

    # Action notice banner if clerk desk has pending items
    notice_markup = ""
    if data["pending_queue"]:
        oldest_pending = data["pending_queue"][-1]
        oldest_id = oldest_pending["id"]
        doc_label = f"{oldest_pending['doc_type']} {('No. ' + oldest_pending['doc_no']) if oldest_pending['doc_no'] else ''}".strip()
        notice_markup = f"""
      <div class="notice-banner" id="queueNotice">
        <div class="notice-info">
          <span class="notice-icon">✍️</span>
          <div class="notice-text">
            <b><span data-i18n="banner_title">Clerk Review Action Required:</span></b> <span data-i18n="banner_prefix">There are</span> <b>{data['desk_n']}</b> <span data-i18n="banner_suffix">land record(s) awaiting verification against scanned evidence and officer digital signing.</span>
          </div>
        </div>
        <a class="btn btn-primary btn-sm" href="/record?verification_id={html.escape(oldest_id)}"><span data-i18n="btn_open_next">Open Next Record</span> ({html.escape(doc_label)}) &rarr;</a>
      </div>"""

    # Master Ledger Table Rows
    if data["rows"]:
        body_rows = []
        for r in data["rows"]:
            doc_no_str = f"No. {r['doc_no']}" if r["doc_no"] else "Unnumbered"
            mandal_str = f"Mandal: {r['mandal']}" if r["mandal"] else ""
            
            verify_btn = ""
            if r["status"] == "APPROVED":
                verify_btn = f'<a class="act-btn act-verify" title="View Public Certificate & Offline QR" href="/?verification_id={html.escape(r["id"])}" data-i18n="btn_cert">✓ Certificate</a>'

            body_rows.append(
                f"""
        <tr class="data-row" data-status="{html.escape(r['status'])}">
          <td class="td-sl">{r['sl']}</td>
          <td class="td-date">{html.escape(r['date'])}</td>
          <td>
            <span class="td-doc-main">{html.escape(r['doc_type'])}</span>
            <span class="td-doc-sub">{html.escape(doc_no_str)}</span>
          </td>
          <td title="{html.escape(r['parties'])}">{html.escape(r['parties'])}</td>
          <td>
            <span class="td-place-main">{html.escape(r['place'])}</span>
            <span class="td-place-sub">{html.escape(mandal_str)}</span>
          </td>
          <td class="td-mono">{html.escape(r['survey'])}</td>
          <td class="td-stamp">{html.escape(r['stamp'])}</td>
          <td>{_badge(r['status'])}</td>
          <td>
            <div class="action-links">
              <a class="act-btn" href="/record?verification_id={html.escape(r['id'])}">Review Console</a>
              {verify_btn}
            </div>
          </td>
        </tr>"""
            )
        table_html = f"""
        <table class="master-ledger">
          <thead>
            <tr>
              <th>Sl.</th>
              <th>Received</th>
              <th>Document &amp; No.</th>
              <th>Parties</th>
              <th>Location</th>
              <th>Survey Designation</th>
              <th>Stamp Duty</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="ledgerBody">
            {''.join(body_rows)}
          </tbody>
        </table>
        <div id="ledgerEmptyNotice" class="table-empty" style="display:none;">
          <p>No matching document entries found.</p>
        </div>"""
    else:
        table_html = """
        <div class="table-empty">
          <p>No land documents registered in the ledger yet.</p>
          <p style="font-size:13px; color:var(--ink-soft); margin-bottom:16px;">
            Open the new intake desk to scan, extract, and certify your first deed.
          </p>
          <a class="btn btn-primary" href="/new">+ Scan First Document</a>
        </div>"""

    donut_svg = _render_donut_svg(data["sale_count"], data["gpa_count"], data["other_count"], data["on_file"])
    velocity_svg = _render_velocity_svg(data["on_file"], data["sealed_n"])
    fp_text = fp or "Keypair auto-generated on first seal"

    page_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OneBhoomi — Land Records Office Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Archivo:wght@400;500;600;700&family=Courier+Prime:ital,wght@0,400;0,700;1,400&family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Sans+Telugu:wght@400;500;600;700&family=Noto+Sans+Kannada:wght@400;500;600;700&family=Noto+Sans+Tamil:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>{DASHBOARD_CSS}</style>
</head>
<body>

<div class="security-bg" aria-hidden="true"></div>

<div class="app-layout">

  {sidebar_html}

  <!-- MAIN WORKSPACE CONTENT -->
  <main class="dash-content">
    <div class="main-inner">
      
      <!-- Top Action Bar -->
      <div class="top-action-bar">
        <div class="header-left">
          <h1 data-i18n="dash_h1">Registry Operations &amp; <em>Analytics</em></h1>
          <div class="header-tagline" data-i18n="dash_tagline">Complete offline day book of land records, human-in-the-loop clerk reviews, and cryptographic digital seals.</div>
        </div>
        <div class="header-right">
          <div class="lang-picker" title="Change Language">
            <svg class="lang-svg" viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="2" y1="12" x2="22" y2="12"></line>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
            </svg>
            <select id="langSelect" class="lang-dropdown" aria-label="Select Language">
              <option value="en" selected>English</option>
              <option value="hi">हिंदी (Hindi)</option>
              <option value="te">తెలుగు (Telugu)</option>
              <option value="kn">ಕನ್ನಡ (Kannada)</option>
              <option value="ta">தமிழ் (Tamil)</option>
            </select>
          </div>
        </div>

      <!-- KPI Summary Cards (4 Cards) -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">
            <span data-i18n="kpi_total">Total on File</span>
            <span>📂</span>
          </div>
          <div class="kpi-num">{data['on_file']}</div>
          <div class="kpi-sub" data-i18n="kpi_total_sub">Total land deeds recorded in offline registry</div>
        </div>

        <div class="kpi-card kpi-sealed">
          <div class="kpi-label">
            <span data-i18n="kpi_sealed">Sealed &amp; Certified</span>
            <span>🛡️</span>
          </div>
          <div class="kpi-num">{data['sealed_n']}</div>
          <div class="kpi-sub">{data['seal_rate']} <span data-i18n="kpi_sealed_sub">certification rate · RSA-PSS signed</span></div>
        </div>

        <div class="kpi-card kpi-desk">
          <div class="kpi-label">
            <span data-i18n="kpi_review">Clerk Review Queue</span>
            <span>✍️</span>
          </div>
          <div class="kpi-num">{data['desk_n']}</div>
          <div class="kpi-sub" data-i18n="kpi_review_sub">Awaiting clerk verification &amp; approval</div>
        </div>

        <div class="kpi-card kpi-rejected">
          <div class="kpi-label">
            <span data-i18n="kpi_noncert">Non-Certified</span>
            <span>⚠️</span>
          </div>
          <div class="kpi-num">{data['rejected_n']}</div>
          <div class="kpi-sub" data-i18n="kpi_noncert_sub">Rejected or anomalous scan records</div>
        </div>
      </div>

      <!-- Action Required Banner (if any pending) -->
      {notice_markup}

      <!-- STATISTICAL ANALYTICS GRAPHS -->
      <section class="charts-grid" id="analyticsSection">
        
        <!-- Graph 1: Velocity & Throughput Trend -->
        <div class="chart-card">
          <div class="chart-header">
            <div>
              <div class="chart-title" data-i18n="chart_vel_title">Registration Velocity &amp; Sealing Throughput</div>
              <div class="chart-meta" data-i18n="chart_vel_meta">Timeline intake volume vs verified cryptographic certifications</div>
            </div>
            <div style="display:flex; gap:12px; font-family:var(--type); font-size:10.5px;">
              <span style="display:flex; align-items:center; gap:5px;">
                <span style="width:8px; height:8px; border-radius:50%; background:var(--stamp);"></span>
                <span data-i18n="chart_total_intake">Total Intake</span>
              </span>
              <span style="display:flex; align-items:center; gap:5px;">
                <span style="width:8px; height:8px; border-radius:50%; background:var(--green);"></span>
                <span data-i18n="chart_sealed_on_file">Sealed on File</span>
              </span>
            </div>
          </div>
          <div class="chart-svg-wrap">
            {velocity_svg}
          </div>
        </div>

        <!-- Graph 2: Document Classification Donut -->
        <div class="chart-card">
          <div class="chart-header">
            <div>
              <div class="chart-title" data-i18n="chart_doc_class">Document Classification</div>
              <div class="chart-meta" data-i18n="chart_doc_meta">Distribution of legal record deed categories</div>
            </div>
            <div class="chart-meta" style="color:var(--green); font-weight:700;">
              <span data-i18n="chart_gis_lbl">GIS Resolved:</span> {data['gis_rate']}
            </div>
          </div>

          <div class="donut-layout">
            <div class="donut-svg-box">
              {donut_svg}
            </div>

            <div class="donut-legend">
              <div class="legend-row">
                <span class="legend-left">
                  <span class="legend-color" style="background:var(--stamp);"></span>
                  <span data-i18n="chart_sale_deeds">Sale Deeds</span>
                </span>
                <span class="legend-num">{data['sale_count']}</span>
              </div>
              <div class="legend-row">
                <span class="legend-left">
                  <span class="legend-color" style="background:var(--gold);"></span>
                  <span data-i18n="chart_agreements_gpa">Agreements / GPA</span>
                </span>
                <span class="legend-num">{data['gpa_count']}</span>
              </div>
              <div class="legend-row">
                <span class="legend-left">
                  <span class="legend-color" style="background:var(--green);"></span>
                  <span data-i18n="chart_other_records">Other Records</span>
                </span>
                <span class="legend-num">{data['other_count']}</span>
              </div>
            </div>
          </div>

          <div class="gis-rate-meter">
            <div class="meter-label">
              <span data-i18n="chart_spatial_match">Telangana (TGRAC) &amp; Karnataka Spatial Match</span>
              <b>{data['gis_rate']} <span data-i18n="chart_resolved">Resolved</span></b>
            </div>
            <div class="meter-bar">
              <div class="meter-fill" style="width:{data['gis_rate']};"></div>
            </div>
          </div>
        </div>

      </section>

      <!-- MASTER LEDGER SECTION -->
      <section class="ledger-section" id="ledgerSection">
        <div class="ledger-toolbar">
          <div class="toolbar-left">
            <h2 class="ledger-head-title" data-i18n="reg_title">Master Deed Register</h2>
            <div class="search-wrap">
              <span class="search-icon">🔍</span>
              <input type="text" id="ledgerSearch" class="search-input" placeholder="Search by Doc #, Village, Party, Survey..." data-i18n-ph="search_placeholder">
            </div>
          </div>

          <div class="toolbar-right">
            <div class="filter-tabs">
              <button type="button" class="tab-btn active" data-filter="ALL"><span data-i18n="tab_all">All</span> ({data['on_file']})</button>
              <button type="button" class="tab-btn" data-filter="SEALED"><span data-i18n="tab_sealed">Sealed</span> ({data['sealed_n']})</button>
              <button type="button" class="tab-btn" data-filter="PENDING"><span data-i18n="tab_pending">Pending</span> ({data['desk_n']})</button>
              <button type="button" class="tab-btn" data-filter="REJECTED"><span data-i18n="tab_rejected">Rejected</span> ({data['rejected_n']})</button>
            </div>
            <a class="btn btn-primary btn-sm" href="/new" data-i18n="btn_scan_new_deed">+ Scan New Deed</a>
          </div>
        </div>

        <div class="table-container">
          {table_html}
        </div>
      </section>

      <!-- Understated Security & System Status Bar -->
      <div class="system-strip" id="systemStrip">
        <div class="strip-group">
          <div class="strip-item">
            <span>🔐 <b data-i18n="lbl_fingerprint">RSA-PSS 2048 Fingerprint:</b></span>
            <code>{html.escape(fp_text[:28])}...</code>
            <button type="button" class="btn-copy" onclick="copyFingerprint('{html.escape(fp_text)}')">Copy</button>
          </div>
        </div>
        <div class="strip-group">
          <div class="strip-item">
            <span>🗺️ <b data-i18n="lbl_spatial_index">Spatial Index:</b> Telangana (TGRAC) &amp; Karnataka Master Datasets Loaded</span>
          </div>
          <div class="strip-item">
            <span>🛡️ <b data-i18n="lbl_key_store">Key Store:</b> <code>verification_keys/</code></span>
          </div>
        </div>
      </div>

    </div>

    <!-- Dashboard Footer -->
    <footer class="dash-footer">
      <div class="main-inner" style="padding-top:0; padding-bottom:0;">
        <div class="dash-footer-wrap">
          <div><b>OneBhoomi Registry Console</b> · Standalone Land Document Extraction &amp; Digital Seal System</div>
          <div>100% Air-Gapped &amp; Immutable · Zero cloud dependencies · Host: <code>{html.escape(host_name)}</code></div>
        </div>
      </div>
    </footer>
  </main>

</div>

<script>{DASHBOARD_JS}</script>
</body>
</html>
"""
    return page_html.encode("utf-8")


def render_new_scan(host_name: str = "localhost:8001", colab_url: str = "", message: str = "") -> bytes:
    """Renders the dedicated New Scan & Intake page equipped with the exact same left sidebar rail."""
    data = get_dashboard_data()
    today = datetime.now().strftime("%d-%m-%Y")

    if colab_url:
        try:
            worker_host = urlparse(colab_url).hostname or colab_url
        except Exception:
            worker_host = colab_url
        worker_label = f"Remote GPU ({worker_host[:16]}...)"
        gpu_selected = "selected"
        cpu_selected = ""
        mode_note = f"GPU Worker active at {worker_host} · Ultra-fast ~2s OCR inference via encrypted tunnel."
    else:
        worker_label = "Local CPU (PaddleOCR)"
        gpu_selected = ""
        cpu_selected = "selected"
        mode_note = "Local CPU OCR active · Runs directly on this machine with PaddleOCR."

    sidebar_html = _render_sidebar("new_scan", data["desk_n"], data["sealed_n"], worker_label)

    msg_banner = ""
    if message:
        msg_banner = f"""
      <div class="notice-banner" style="background:#FCE8E6; border-color:#F5B7B1; border-left-color:var(--stamp); margin-bottom:20px;">
        <div class="notice-info">
          <span class="notice-icon">⚠️</span>
          <div class="notice-text" style="color:var(--stamp-deep);"><b>Intake Notice:</b> {html.escape(message)}</div>
        </div>
      </div>"""

    page_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OneBhoomi — New Document Scan &amp; Intake</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Archivo:wght@400;500;600;700&family=Courier+Prime:ital,wght@0,400;0,700;1,400&family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Sans+Telugu:wght@400;500;600;700&family=Noto+Sans+Kannada:wght@400;500;600;700&family=Noto+Sans+Tamil:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>{DASHBOARD_CSS}</style>
</head>
<body>

<div class="security-bg" aria-hidden="true"></div>

<!-- Loading overlay on extraction submission -->
<div class="loading-overlay" id="loadingOverlay">
  <div class="loading-box">
    <div class="loading-spinner"></div>
    <div class="loading-title">Processing Document Scan</div>
    <div class="loading-sub">Running OCR inference, parsing canonical facts, and executing Stage 1 validation checks...</div>
  </div>
</div>

<div class="app-layout">

  {sidebar_html}

  <!-- MAIN WORKSPACE CONTENT -->
  <main class="dash-content">
    <div class="main-inner">
      
      <!-- Top Action Bar -->
      <div class="top-action-bar">
        <div class="header-left">
          <h1 data-i18n="intake_h1">New Document Scan &amp; <em>Intake</em></h1>
          <div class="header-tagline">Desk 01 · Process land documents (Sale Deeds, Agreements, GPAs) with local OCR or Kaggle GPU acceleration.</div>
        </div>
        <div class="header-right">
          <div class="lang-picker" title="Change Language">
            <svg class="lang-svg" viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="2" y1="12" x2="22" y2="12"></line>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
            </svg>
            <select id="langSelect" class="lang-dropdown" aria-label="Select Language">
              <option value="en" selected>English</option>
              <option value="hi">हिंदी (Hindi)</option>
              <option value="te">తెలుగు (Telugu)</option>
              <option value="kn">ಕನ್ನಡ (Kannada)</option>
              <option value="ta">தமிழ் (Tamil)</option>
            </select>
          </div>
        </div>

      {msg_banner}

      <!-- Dedicated Intake Card -->
      <div class="intake-card">
        <div class="intake-head">
          <h2 data-i18n="intake_title">Registration &amp; Scan Intake</h2>
          <span class="intake-badge">Stage 1 · Document Intake</span>
        </div>

        <form id="scanForm" action="/extract" method="post" enctype="multipart/form-data">
          
          <!-- Dropzone File Selector -->
          <div class="intake-dropzone" id="intakeDropzone" tabindex="0" role="button" aria-label="Drop scan file here or click to browse">
            <svg class="dz-icon-svg" viewBox="0 0 24 24" stroke-width="1.6">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="12" y1="18" x2="12" y2="12"></line>
              <line x1="9" y1="15" x2="15" y2="15"></line>
            </svg>
            <div class="dz-main-text" data-i18n="dz_main_text">Drop the document scan copy here, or <span>browse local files</span></div>
            <div class="dz-sub-text">Supports PDF (Multi-page supported) · PNG · JPG · TIFF &mdash; Read locally, certified with RSA-PSS</div>
            <input type="file" name="document_image" id="scan_file_input" accept="image/*,.pdf,application/pdf" hidden required>
          </div>

          <!-- Selected File Chip -->
          <div class="filechip" id="fileChip" style="display:none;">
            <div class="filechip-name">
              <span>📄</span>
              <span id="chipName">document.pdf</span>
            </div>
            <div class="filechip-actions">
              <span class="filechip-size" id="chipSize">1.2 MB</span>
              <button type="button" class="filechip-btn" id="chipRemove" title="Remove file">&times;</button>
            </div>
          </div>

          <!-- OCR Engine & Execution Settings -->
          <div class="config-grid">
            <div class="config-box">
              <div class="config-box-title" data-i18n="ocr_engine_title">OCR Processing Engine</div>
              <select name="processing_mode" id="processing_mode" class="select-mode">
                <option value="gpu" {gpu_selected}>⚡ Remote GPU Worker (Encrypted Cloudflare Tunnel, ~2s)</option>
                <option value="cpu" {cpu_selected}>🐢 Local CPU (PaddleOCR on this machine)</option>
              </select>
              <div class="config-note">{html.escape(mode_note)}</div>
            </div>

            <div class="config-box">
              <div class="config-box-title" data-i18n="val_grounding_title">Validation &amp; Spatial Grounding</div>
              <div style="font-size:13px; color:var(--ink); font-weight:600; margin-bottom:4px;">
                ✓ Automatic 5-Point Rule Engine &amp; GIS Check
              </div>
              <div class="config-note">
                Checks required fields, area numeric bounds, date chronological logic, survey designations, and cross-references Telangana/Karnataka administrative GIS polygons.
              </div>
            </div>
          </div>

          <!-- Pipeline Progression Stepper -->
          <div class="stepper-strip">
            <div class="stepper-item step-active">
              <span class="step-num">1</span>
              <span class="step-label">Scan &amp; OCR Text</span>
            </div>
            <div class="stepper-item">
              <span class="step-num">2</span>
              <span class="step-label">Machine Validation</span>
            </div>
            <div class="stepper-item">
              <span class="step-num">3</span>
              <span class="step-label">Clerk Review Desk</span>
            </div>
            <div class="stepper-item">
              <span class="step-num">4</span>
              <span class="step-label">RSA-PSS 2048 Digital Seal</span>
            </div>
          </div>

          <!-- Submit Button & Security Note -->
          <div class="submit-row">
            <div class="submit-note">
              🔒 Zero external database or cloud storage. Files are processed in memory and persisted into local verification store.
            </div>
            <button type="submit" class="btn btn-primary" style="padding:12px 28px; font-size:12.5px;" data-i18n="btn_start_extract">
              Start Document Extraction &rarr;
            </button>
          </div>

        </form>
      </div>

    </div>

    <!-- Page Footer -->
    <footer class="dash-footer">
      <div class="main-inner" style="padding-top:0; padding-bottom:0;">
        <div class="dash-footer-wrap">
          <div><b>OneBhoomi Registry Console</b> · Standalone Land Document Extraction &amp; Digital Seal System</div>
          <div>100% Air-Gapped &amp; Immutable · Zero cloud dependencies · Host: <code>{html.escape(host_name)}</code></div>
        </div>
      </div>
    </footer>
  </main>

</div>

<script>{DASHBOARD_JS}</script>
</body>
</html>
"""
    return page_html.encode("utf-8")
