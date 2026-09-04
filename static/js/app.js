/* ============================================
   Ganfeng Fiberglass · 独立站主交互
   - 加载产品列表
   - 询盘表单提交
   - 多语言切换
   ============================================ */
(function(){
'use strict';

// 多语言词典（独立站关键文案）
const I18N = {
  zh: {
    heroBadge: '🏆 18年出口工厂 · ISO 9001 认证',
    heroTitle: '为全球 <span style="color:var(--warm)">外墙保温 / 防水 / GRC</span> 提供工厂直供玻纤网格布',
    heroSub: '12 SKU 全场景、8000 吨年产能、出口 50+ 国家。免费样品，24h 报价。',
    capacity:'产能', countries:'国家', history:'历史', alkali:'抗碱率',
    ctaQuote:'📋 立即询盘',
    ctaChat:'💬 AI 客服对话',
    sectionProducts: '12 SKU 全场景覆盖 · 一次询盘搞定全品类',
    sectionProductsSub: '从外墙保温到海洋防腐，从防水卷材到 GRC 装饰 — 12 款规格满足所有玻纤网格布采购需求。',
    sectionApps: '从外墙到海洋，您的项目全程解决方案',
    sectionFactory: '江西赣州 · 12 条织造线 + 5 条涂层线',
    factoryDesc: '距离宁波港 600 km / 深圳港 500 km，可同时辐射华东与华南出口。',
    formName:'您的姓名', formEmail:'邮箱', formCountry:'国家', formMessage:'留言',
    formCompany:'公司', formPhone:'WhatsApp / 电话', formSku:'目标 SKU',
    formQtyRolls:'需求卷数', formQtySqm:'需求面积', formSubmit:'提交询盘'
  },
  en: {
    heroBadge: '🏆 18 Years Exporter · ISO 9001 Certified',
    heroTitle: 'Factory-Direct Fiberglass Mesh for <span style="color:var(--warm)">EWI / Waterproofing / GRC</span> Worldwide',
    heroSub: '12 SKU lineup, 8,000-ton capacity, shipped to 50+ countries. Free samples, 24h quotation.',
    capacity:'Capacity', countries:'Countries', history:'History', alkali:'Alkali Resist.',
    ctaQuote:'📋 Get a Quote',
    ctaChat:'💬 Chat with AI Expert',
    sectionProducts: '12 SKU Full-Scenario Coverage · One Quote, Full Lineup',
    sectionProductsSub: 'From external wall insulation to marine anti-corrosion, waterproofing membrane to GRC decoration — 12 specs cover all fiberglass mesh needs.',
    sectionApps: 'From Wall Insulation to Marine Projects, Full Lifecycle Coverage',
    sectionFactory: 'Ganzhou, Jiangxi · 12 Weaving Lines + 5 Coating Lines',
    factoryDesc: '600 km from Ningbo Port / 500 km from Shenzhen Port — covers both East and South China exports.',
    formName:'Your Name', formEmail:'Email', formCountry:'Country', formMessage:'Message',
    formCompany:'Company', formPhone:'WhatsApp / Phone', formSku:'Target SKU',
    formQtyRolls:'Quantity (rolls)', formQtySqm:'Area (m²)', formSubmit:'Submit Inquiry'
  }
};

let currentLang = 'zh';

window.switchLang = function(lang){
  currentLang = lang;
  const t = I18N[lang];
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key = el.getAttribute('data-i18n');
    if (t[key]) el.innerHTML = t[key];
  });
  document.title = lang === 'zh' ? '赣丰玻纤 · Ganfeng Fiberglass' : 'Ganfeng Fiberglass · Fiberglass Mesh Exporter';
  loadProducts(); // 重新加载产品列表
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
  grid.innerHTML = data.products.map(p => {
    const price = p.target_price_usd_per_sqm
      ? `<strong>USD ${p.target_price_usd_per_sqm.toFixed(2)}</strong>/m²`
      : '<strong>Negotiable</strong>';
    return `
      <div class="product-card">
        <span class="pc-sku">${p.sku}</span>
        <div class="pc-name">${p.name}</div>
        <div class="pc-spec">
          <div><span>克重/Gram</span><strong>${p.gram || '—'}${typeof p.gram === 'number' ? ' g' : ''}</strong></div>
          <div><span>网孔/Mesh</span><strong>${p.mesh_size || '—'}</strong></div>
          <div><span>幅宽/Width</span><strong>${p.width || '—'}</strong></div>
          <div><span>卷长/Roll</span><strong>${p.length_per_roll || '—'}</strong></div>
          <div><span>经向/Warp</span><strong>${p.tensile_strength_warp || '—'}</strong></div>
          <div><span>纬向/Weft</span><strong>${p.tensile_strength_weft || '—'}</strong></div>
          <div><span>抗碱</span><strong>${p.alkali_resistance_pct || '—'}%</strong></div>
          <div><span>交期/Lead</span><strong>${p.lead_time_days || 20} 天</strong></div>
        </div>
        <div class="pc-tag-row">
          ${p.applications.slice(0, 2).map(a => `<span class="pc-tag app">${a}</span>`).join('')}
          ${(p.scenarios || []).slice(0, 2).map(s => `<span class="pc-tag">${s}</span>`).join('')}
        </div>
        <div class="pc-action">
          <div class="pc-price">${price}<div class="pc-moq">MOQ ${p.moq_rolls} rolls</div></div>
          <a href="#quote-form" class="pc-quote" onclick="preSelectSku('${p.sku}')">询盘→</a>
        </div>
      </div>
    `;
  }).join('');

  // 同时填充 SKU select
  const sel = document.getElementById('sku-select');
  if (sel){
    sel.innerHTML = '<option value="">未指定（让顾问推荐）</option>' +
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
    result.textContent = '提交中... / Submitting...';

    try{
      const res = await fetch('/api/inquiry', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const json = await res.json();
      if (json.status === 'ok'){
        result.className = 'inquiry-result ok';
        result.innerHTML = '✅ <strong>询盘已收到！</strong>Inquiry submitted!<br>询盘编号 #' + json.inquiry_id + ' · 24h 内会有外贸专员联系您。<br>A specialist will contact you within 24h.';
        form.reset();
      } else {
        result.className = 'inquiry-result err';
        result.textContent = '提交失败：' + (json.msg || '未知错误');
      }
    } catch(err){
      result.className = 'inquiry-result err';
      result.textContent = '网络错误：' + err.message;
    }
  });
}

// 语言切换
const langBtn = document.getElementById('lang-toggle');
if (langBtn){
  langBtn.addEventListener('click', () => {
    switchLang(currentLang === 'zh' ? 'en' : 'zh');
    langBtn.textContent = currentLang === 'zh' ? 'EN / 中' : 'ZH / EN';
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
  loadProducts();
});

})();
