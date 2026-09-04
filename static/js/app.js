/* ============================================
   Ganfeng Fiberglass · 独立站主交互
   - 加载产品列表
   - 询盘表单提交
   - 多语言切换 (EN / ZH)
   ============================================ */
(function(){
'use strict';

const I18N = {
  en: {
    // nav + header
    navProducts: 'Products',
    navHowToOrder: 'How to Order',
    navApplications: 'Applications',
    navFactory: 'Factory',
    navContact: 'Contact',
    getQuote: '📋 Get Quote',

    // hero
    heroBadge: '🏆 18 Years Exporter · ISO 9001 Certified',
    heroTitle: 'Factory-Direct Fiberglass Mesh for <span style="color:var(--warm)">EWI / Waterproofing / GRC</span> Worldwide',
    heroSub: '12 SKU lineup, 8,000-ton capacity, shipped to 50+ countries. Free samples, 24h quotation.',
    capacity: 'Capacity',
    countries: 'Countries',
    history: 'History',
    alkali: 'Alkali Resist.',
    ctaQuote: '📋 Get a Quote',
    ctaChat: '💬 Chat with AI Expert',

    // why us
    whyTag: 'WHY GANFENG',
    whyTitle: 'Why 300+ Overseas Buyers Keep Coming Back',
    whySub: '18 years of factory-direct exporting. From sampling to shipping, every step is under control — verify it with one order.',
    why1Title: 'Factory Direct · No Middleman',
    why1Desc: 'Own weaving & coating plant in Ganzhou, Jiangxi. 8,000 tons/year capacity, FOB Ningbo / Shanghai.',
    why2Title: '24h Quote · 7-Day Sample',
    why2Desc: 'Formal quotation within 24h for standard specs; free samples sent within 7 days (DHL / FedEx).',
    why3Title: 'Global Certifications',
    why3Desc: 'ISO 9001 / ISO 14001, CE, RoHS, EN 13496, ASTM B117 reports available with shipment.',
    why4Title: '50+ Countries · On-Time Delivery',
    why4Desc: 'Long-term clients in Middle East, Europe, SE Asia, Latin America. 30+ containers/month, 96% on-time.',

    // process
    processTag: 'HOW TO ORDER',
    processTitle: '4 Steps from Inquiry to Shipment',
    processSub: 'Submit request → AI assistant confirms → receive formal quote → production & shipping. Fully traceable.',
    process1Title: 'Submit Inquiry',
    process1Desc: 'Fill in specs, quantity, and destination port — submit in 1 minute.',
    process2Title: 'AI Assistant',
    process2Desc: 'AI recognizes your needs and recommends SKUs; complex cases are routed to human follow-up.',
    process3Title: 'Confirm Quote',
    process3Desc: 'Receive a formal quote with FOB/CIF, lead time, and payment terms within 24h.',
    process4Title: 'Produce & Ship',
    process4Desc: 'Scheduling, QC, loading. Average lead time 18 days. Logistics fully traceable.',

    // products
    productsTag: 'PRODUCTS',
    sectionProducts: '12 SKU Full-Scenario Coverage · One Quote, Full Lineup',
    sectionProductsSub: 'From external wall insulation to marine anti-corrosion, waterproofing membrane to GRC decoration — 12 specs cover all fiberglass mesh needs.',

    // applications
    appsTag: 'APPLICATIONS',
    appsTitle: 'From Wall Insulation to Marine Projects, Full Lifecycle Coverage',
    scenario1Title: 'External Wall Insulation',
    scenario1Desc: 'EIFS / ETICS systems, global standard specs, 145-160g alkali-resistant mesh.',
    scenario2Title: 'Waterproofing Membrane',
    scenario2Desc: 'Reinforcement for waterproof rolls, 160-280g mesh compatible with bitumen.',
    scenario3Title: 'GRC Decoration',
    scenario3Desc: 'Permanent GRC buildings, 220g high alkali-resistant mesh, standard for decorative components.',
    scenario4Title: 'Marine Anti-Corrosion',
    scenario4Desc: 'Marine engineering anti-corrosion, 200g salt-alkali resistant coating, ASTM B117 1000h.',
    scenario5Title: 'Solar PV Reinforcement',
    scenario5Desc: 'PV backsheet and offshore PV platforms, 180g UV-resistant coating, high-growth category.',
    scenario6Title: 'Drywall Joint',
    scenario6Desc: 'Gypsum board joints and crack repair, 75-120g self-adhesive joint tape, mainstream in North America & Europe.',

    // factory
    factoryTag: '🏭 FACTORY',
    factoryTitle: 'Ganzhou, Jiangxi · 12 Weaving Lines + 5 Coating Lines',
    factoryDesc: '600 km from Ningbo Port / 500 km from Shenzhen Port — covers both East and South China exports.',
    factoryISO9001: 'ISO 9001:2015 Quality Management System',
    factoryISO14001: 'ISO 14001:2015 Environmental Management System',
    factoryCE: 'CE / RoHS / EN 13496 Tested',
    factoryVideo: 'WhatsApp / WeChat Video Factory Tour',
    factorySGS: 'Third-party SGS / BV Test Reports Available',
    factoryCapacity: 'Tons / Year Capacity',
    factoryLines: 'Weaving + Coating Lines',
    factoryOutput: 'sqm / Year Output',
    factoryClients: 'Active Overseas Clients',

    // quote form
    inquiryTag: '📋 INQUIRY',
    inquiryTitle: 'Submit Inquiry in 1 Min · Reply Within 24h',
    inquirySub: 'Your inquiry enters the AI assistant channel and is pushed to the export team Feishu group.',
    formName: 'Your Name',
    formCompany: 'Company',
    formEmail: 'Email',
    formPhone: 'WhatsApp / Phone',
    formCountry: 'Country',
    formSku: 'Target Product',
    formSkuPlaceholder: 'Not specified (let our specialist recommend)',
    formQtyRolls: 'Quantity (rolls)',
    formQtySqm: 'Area (m²)',
    formMessage: 'Message',
    formMessagePlaceholder: 'Describe your project type, spec requirements, special coating, lead time, etc.',
    formSubmit: '📋 Submit Inquiry',
    formSubmitting: 'Submitting...',
    formOk: '<strong>Inquiry received!</strong><br>Inquiry #{{id}} · A specialist will contact you within 24h.',
    formErr: 'Submission failed: ',
    formNetworkErr: 'Network error: ',

    // chatbot
    chatTitle: '🤖 Ganfeng AI Expert',
    chatStatus: '● Online · 24h Replies',
    chatWelcome: '👋 Hi! I\'m Ganfeng\'s AI assistant. Ask me about <strong>products, MOQ, samples, lead time, certifications, payment, shipping</strong> — or any question about fiberglass mesh.',
    chatQuick1: 'MOQ 145g?',
    chatQuick2: 'Free Samples?',
    chatQuick3: 'Lead Time',
    chatQuick4: 'Certs',
    chatPlaceholder: 'Type your question...',
    chatSend: 'Send',
    chatTyping: 'AI is typing...',

    // footer
    footerProducts: 'Products',
    footerResources: 'Resources',
    footerCompliance: 'Compliance',
    footerAdmin: '📊 Admin Dashboard',
    footerInquiry: '📋 Submit Inquiry',
    footerProductsLink: '🏭 Products',
    footerHowToOrder: '🔄 How to Order',
    footerCopyright: '© 2026 Ganfeng Fiberglass Mesh Co., Ltd. · 18 Years in Fiberglass Reinforcement'
  },
  zh: {
    // nav + header
    navProducts: '产品',
    navHowToOrder: '采购流程',
    navApplications: '应用场景',
    navFactory: '工厂',
    navContact: '联系我们',
    getQuote: '📋 立即询盘',

    // hero
    heroBadge: '🏆 18年出口工厂 · ISO 9001 认证',
    heroTitle: '为全球 <span style="color:var(--warm)">外墙保温 / 防水 / GRC</span> 提供工厂直供玻纤网格布',
    heroSub: '12 SKU 全场景、8000 吨年产能、出口 50+ 国家。免费样品，24h 报价。',
    capacity: '产能',
    countries: '国家',
    history: '历史',
    alkali: '抗碱率',
    ctaQuote: '📋 立即询盘',
    ctaChat: '💬 AI 客服对话',

    // why us
    whyTag: '核心优势',
    whyTitle: '300+ 海外买家持续复购的理由',
    whySub: '18 年出口工厂直供，从打样到发货全流程可控，一次合作即可验证。',
    why1Title: '工厂直供 · 无中间商',
    why1Desc: '江西赣州自有织造 + 涂层基地，8000 吨年产能，FOB 宁波/上海直发。',
    why2Title: '24h 报价 · 7 天打样',
    why2Desc: '常规规格 24h 内出正式报价，免费样品 7 天内寄出（DHL / FedEx）。',
    why3Title: '全球认证 · 合规出口',
    why3Desc: 'ISO 9001 / ISO 14001、CE、RoHS、EN 13496、ASTM B117 报告可随货提供。',
    why4Title: '50+ 国家 · 稳定交付',
    why4Desc: '中东、欧洲、东南亚、拉美长期客户，月均交付 30+ 货柜，交期准点率 96%。',

    // process
    processTag: '4 步轻松采购',
    processTitle: '从询盘到发货，只需 4 步',
    processSub: '提交需求 → AI 客服确认 → 收到正式报价 → 生产排期发货，全程可追踪。',
    process1Title: '提交询盘',
    process1Desc: '填写产品规格、数量、目标港口，1 分钟完成提交。',
    process2Title: 'AI 客服确认',
    process2Desc: 'AI 自动识别需求、推荐 SKU，复杂问题转人工跟进。',
    process3Title: '确认报价',
    process3Desc: '24h 内收到含 FOB / CIF、交期、付款方式的正式报价单。',
    process4Title: '生产 & 发货',
    process4Desc: '下单后排产、质检、装柜，平均交期 18 天，物流可追踪。',

    // products
    productsTag: '产品矩阵',
    sectionProducts: '12 SKU 全场景覆盖 · 一次询盘搞定全品类',
    sectionProductsSub: '从外墙保温到海洋防腐，从防水卷材到 GRC 装饰 — 12 款规格满足所有玻纤网格布采购需求。',

    // applications
    appsTag: '应用场景',
    appsTitle: '从外墙到海洋，您的项目全程解决方案',
    scenario1Title: '外墙保温系统',
    scenario1Desc: '外墙保温系统（EIFS/ETICS），是全球通用规格，145-160g 抗碱网格布。',
    scenario2Title: '防水卷材增强',
    scenario2Desc: '防水卷材增强，160-280g 网格布与沥青相容，应用于屋面与卫生间。',
    scenario3Title: 'GRC 装饰构件',
    scenario3Desc: 'GRC 永久性建筑，220g 高抗碱率网格布，欧美装饰构件标准配置。',
    scenario4Title: '海洋工程防腐',
    scenario4Desc: '海洋工程防腐，200g 耐盐碱涂层，ASTM B117 1000h 盐雾测试。',
    scenario5Title: '光伏组件增强',
    scenario5Desc: '光伏组件背板与海上光伏平台，180g 耐 UV 涂层，未来高增长品类。',
    scenario6Title: '石膏板接缝',
    scenario6Desc: '石膏板接缝与裂缝修补，75-120g 自粘接缝带，北美欧洲主流产品。',

    // factory
    factoryTag: '🏭 工厂实景',
    factoryTitle: '江西赣州 · 12 条织造线 + 5 条涂层线',
    factoryDesc: '距离宁波港 600 km / 深圳港 500 km，可同时辐射华东与华南出口。',
    factoryISO9001: 'ISO 9001:2015 质量管理体系',
    factoryISO14001: 'ISO 14001:2015 环境管理体系',
    factoryCE: 'CE / RoHS / EN 13496 测试合格',
    factoryVideo: '支持 WhatsApp/WeChat 视频验厂',
    factorySGS: '第三方 SGS/BV 测试报告可出',
    factoryCapacity: '吨 / 年产能',
    factoryLines: '织造 + 涂层线',
    factoryOutput: '平米 / 年产量',
    factoryClients: '活跃海外客户',

    // quote form
    inquiryTag: '📋 询盘表单',
    inquiryTitle: '1 分钟提交询盘 · 24h 内外贸专员回复',
    inquirySub: '提交后将进入 AI 客服通道，自动识别您的需求并推送至外贸部飞书群。',
    formName: '您的姓名',
    formCompany: '公司',
    formEmail: '邮箱',
    formPhone: 'WhatsApp / 电话',
    formCountry: '国家',
    formSku: '目标 SKU',
    formSkuPlaceholder: '未指定（让顾问推荐）',
    formQtyRolls: '需求卷数',
    formQtySqm: '需求面积',
    formMessage: '留言',
    formMessagePlaceholder: '请描述您的项目类型、规格要求、特殊涂层、交期等',
    formSubmit: '📋 提交询盘',
    formSubmitting: '提交中...',
    formOk: '✅ <strong>询盘已收到！</strong><br>询盘编号 #{{id}} · 24h 内会有外贸专员联系您。',
    formErr: '提交失败：',
    formNetworkErr: '网络错误：',

    // chatbot
    chatTitle: '🤖 Ganfeng AI 客服',
    chatStatus: '● 在线 · 24h 回复',
    chatWelcome: '👋 您好！我是赣丰玻纤 AI 客服。可咨询 <strong>产品、MOQ、样品、交期、认证、付款、物流</strong> 等任何问题。',
    chatQuick1: '145g MOQ?',
    chatQuick2: '免费样品?',
    chatQuick3: '交期多久',
    chatQuick4: '认证资质',
    chatPlaceholder: '输入您的问题...',
    chatSend: '发送',
    chatTyping: 'AI 正在输入...',

    // footer
    footerProducts: '产品',
    footerResources: '资源',
    footerCompliance: '合规',
    footerAdmin: '📊 内部选品看板',
    footerInquiry: '📋 提交询盘',
    footerProductsLink: '🏭 产品',
    footerHowToOrder: '🔄 采购流程',
    footerCopyright: '© 2026 赣丰玻纤网格布有限公司 · 18 年专注玻纤增强材料'
  }
};

let currentLang = 'en';

// 暴露给 chatbot.js 使用
window.GF_I18N = I18N;
window.GF_CURRENT_LANG = function(){ return currentLang; };

function applyStaticText(){
  const t = I18N[currentLang];
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key = el.getAttribute('data-i18n');
    if (t[key] !== undefined){
      // 对 placeholder / value 等属性单独处理
      if (el.hasAttribute('placeholder')){
        el.setAttribute('placeholder', t[key]);
      } else if (el.tagName === 'BUTTON' && (el.type === 'submit' || el.value)){
        el.innerHTML = t[key];
      } else {
        el.innerHTML = t[key];
      }
    }
  });
}

window.switchLang = function(lang){
  if (!I18N[lang]) return;
  currentLang = lang;
  const t = I18N[lang];

  applyStaticText();
  loadProducts();

  // 切换按钮显示目标语言
  const btn = document.getElementById('lang-toggle');
  if (btn){
    btn.textContent = currentLang === 'en' ? '中 / ZH' : 'EN';
  }

  // 页面标题
  document.title = lang === 'zh' ? '赣丰玻纤 · Ganfeng Fiberglass' : 'Ganfeng Fiberglass · Fiberglass Mesh Exporter';

  // html lang 属性
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
};

// 加载产品列表
async function loadProducts(){
  const res = await fetch('/api/products?lang=' + currentLang);
  const data = await res.json();
  const grid = document.getElementById('products-grid');
  if (!data.products || data.products.length === 0){
    grid.innerHTML = '<div class="loading">No products yet.</div>';
    return;
  }
  const t = I18N[currentLang];
  grid.innerHTML = data.products.map(p => {
    const price = p.target_price_usd_per_sqm
      ? `<strong>USD ${p.target_price_usd_per_sqm.toFixed(2)}</strong>/m²`
      : `<strong>${currentLang === 'zh' ? '面议' : 'Negotiable'}</strong>`;
    const moqLabel = currentLang === 'zh' ? '起订' : 'MOQ';
    const inqLabel = currentLang === 'zh' ? '询盘→' : 'Quote→';
    const gramLabel = currentLang === 'zh' ? '克重' : 'Gram';
    const meshLabel = currentLang === 'zh' ? '网孔' : 'Mesh';
    const widthLabel = currentLang === 'zh' ? '幅宽' : 'Width';
    const rollLabel = currentLang === 'zh' ? '卷长' : 'Roll';
    const warpLabel = currentLang === 'zh' ? '经向' : 'Warp';
    const weftLabel = currentLang === 'zh' ? '纬向' : 'Weft';
    const alkaliLabel = currentLang === 'zh' ? '抗碱' : 'Alkali';
    const leadLabel = currentLang === 'zh' ? '交期' : 'Lead';
    const daysLabel = currentLang === 'zh' ? '天' : 'days';
    return `
      <div class="product-card">
        <span class="pc-sku">${p.sku}</span>
        <div class="pc-name">${p.name}</div>
        <div class="pc-spec">
          <div><span>${gramLabel}</span><strong>${p.gram || '—'}${typeof p.gram === 'number' ? ' g' : ''}</strong></div>
          <div><span>${meshLabel}</span><strong>${p.mesh_size || '—'}</strong></div>
          <div><span>${widthLabel}</span><strong>${p.width || '—'}</strong></div>
          <div><span>${rollLabel}</span><strong>${p.length_per_roll || '—'}</strong></div>
          <div><span>${warpLabel}</span><strong>${p.tensile_strength_warp || '—'}</strong></div>
          <div><span>${weftLabel}</span><strong>${p.tensile_strength_weft || '—'}</strong></div>
          <div><span>${alkaliLabel}</span><strong>${p.alkali_resistance_pct || '—'}%</strong></div>
          <div><span>${leadLabel}</span><strong>${p.lead_time_days || 20} ${daysLabel}</strong></div>
        </div>
        <div class="pc-tag-row">
          ${p.applications.slice(0, 2).map(a => `<span class="pc-tag app">${a}</span>`).join('')}
          ${(p.scenarios || []).slice(0, 2).map(s => `<span class="pc-tag">${s}</span>`).join('')}
        </div>
        <div class="pc-action">
          <div class="pc-price">${price}<div class="pc-moq">${moqLabel} ${p.moq_rolls} rolls</div></div>
          <a href="#quote-form" class="pc-quote" onclick="preSelectSku('${p.sku}')">${inqLabel}</a>
        </div>
      </div>
    `;
  }).join('');

  // 同时填充 SKU select
  const sel = document.getElementById('sku-select');
  if (sel){
    sel.innerHTML = `<option value="">${t.formSkuPlaceholder}</option>` +
      data.products.map(p => `<option value="${p.sku}">${p.sku} · ${p.name_zh}</option>`).join('');
  }
}

window.preSelectSku = function(sku){
  const sel = document.getElementById('sku-select');
  if (sel){
    sel.value = sku;
    document.getElementById('quote-form').scrollIntoView({behavior:'smooth'});
  }
};

// 询盘表单提交
const form = document.getElementById('inquiryForm');
const result = document.getElementById('inquiry-result');
if (form){
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = {};
    fd.forEach((v, k) => { payload[k] = v || null; });
    result.style.display = 'block';
    result.className = 'inquiry-result';
    result.textContent = I18N[currentLang].formSubmitting;

    try{
      const res = await fetch('/api/inquiry', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const json = await res.json();
      if (json.status === 'ok'){
        result.className = 'inquiry-result ok';
        result.innerHTML = I18N[currentLang].formOk.replace('{{id}}', json.inquiry_id);
        form.reset();
      } else {
        result.className = 'inquiry-result err';
        result.textContent = I18N[currentLang].formErr + (json.msg || 'unknown error');
      }
    } catch(err){
      result.className = 'inquiry-result err';
      result.textContent = I18N[currentLang].formNetworkErr + err.message;
    }
  });
}

// 语言切换
const langBtn = document.getElementById('lang-toggle');
if (langBtn){
  langBtn.addEventListener('click', () => {
    switchLang(currentLang === 'en' ? 'zh' : 'en');
  });
}

// Chatbot 全局函数
window.openChat = function(){
  const win = document.getElementById('chat-window');
  win.classList.add('show');
  setTimeout(() => document.getElementById('chat-input').focus(), 100);
};
window.toggleChat = function(){
  const win = document.getElementById('chat-window');
  if (win.classList.contains('show')) win.classList.remove('show');
  else openChat();
};
window.chatQuick = function(msg){
  document.getElementById('chat-input').value = msg;
  document.getElementById('chat-form').dispatchEvent(new Event('submit'));
};

// 启动加载
document.addEventListener('DOMContentLoaded', () => {
  // 默认英文，与 HTML 文案保持一致
  switchLang('en');
});

})();
