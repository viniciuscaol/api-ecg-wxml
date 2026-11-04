/** ECG Viewer 1.1.0. Web Component sem dependências; mantém o SVG vetorial como <img>.
 * Uso: import '/assets/ecg-viewer.js'; await document.querySelector('ecg-viewer').load(svgBlob);
 * 100% significa ajustar à largura do painel, não uma escala clínica de monitor.
 */
export class EcgViewer extends HTMLElement {
  constructor() {
    super();
    this.zoom = 1;
    this.url = null;
    this.drag = null;
    this.loadId = 0;
    this.ready = false;
    this.attachShadow({mode: 'open'}).innerHTML = `
      <style>
        :host{display:block;font:14px system-ui;color:#183b3b}:host([hidden]){display:none}
        *{box-sizing:border-box}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px;background:#eaf2f2;border:1px solid #cfdddd;border-radius:10px 10px 0 0}
        button{font:inherit;background:white;border:1px solid #b9cecd;padding:7px 12px;border-radius:6px;color:inherit;cursor:pointer}button:disabled{opacity:.4;cursor:default}
        output{min-width:56px;text-align:center}.tip{font-size:12px;color:#526b6b}
        .viewport{width:100%;height:var(--ecg-height,70vh);min-height:280px;overflow:auto;background:#dce5e5;border:1px solid #cfdddd;overscroll-behavior:contain;cursor:grab;touch-action:pan-x pan-y}
        .viewport.dragging{cursor:grabbing}.viewport:focus-visible{outline:3px solid #00897d}
        img{display:block;max-width:none;height:auto;user-select:none;-webkit-user-drag:none;background:white}
        img[hidden]{display:none}.empty{padding:24px;text-align:center}.note{font-size:12px;padding:8px;background:#f3f7f7}
      </style>
      <div class="toolbar" role="toolbar" aria-label="Zoom do ECG">
        <button data-action="out" aria-label="Diminuir zoom" disabled>−</button><output aria-live="polite">100%</output>
        <button data-action="in" aria-label="Aumentar zoom" disabled>+</button><button data-action="fit" disabled>Ajustar largura</button>
        <span class="tip">Ctrl + roda: zoom · Arraste ou use as barras para navegar</span>
      </div>
      <div class="viewport" tabindex="0" role="region" aria-label="Traçado ECG com zoom e rolagem">
        <div class="empty">Carregue um WXML para visualizar o traçado.</div><img hidden alt="ECG vetorial com 12 derivações" draggable="false">
      </div>
      <div class="note">Zoom de exibição: 100% ajusta à largura. Não representa calibração física do monitor.</div>`;
    const s = this.shadowRoot;
    this.viewport = s.querySelector('.viewport');
    this.image = s.querySelector('img');
    this.output = s.querySelector('output');
    s.querySelector('[data-action=in]').addEventListener('click', () => this.setZoom(this.zoom*1.25));
    s.querySelector('[data-action=out]').addEventListener('click', () => this.setZoom(this.zoom/1.25));
    s.querySelector('[data-action=fit]').addEventListener('click', () => {this.setZoom(1);this.viewport.scrollTo(0,0);});
    this.viewport.addEventListener('wheel', event => {
      if (!event.ctrlKey || !this.ready) return;
      event.preventDefault();
      const rect = this.viewport.getBoundingClientRect();
      this.setZoom(this.zoom*Math.exp(-event.deltaY*.002), event.clientX-rect.left, event.clientY-rect.top);
    }, {passive:false});
    this.viewport.addEventListener('pointerdown', event => {
      if (!this.ready || event.button!==0 || event.pointerType!=='mouse') return;
      // Não captura a barra de rolagem nativa.
      const rect=this.viewport.getBoundingClientRect();
      if(event.clientX-rect.left>this.viewport.clientWidth || event.clientY-rect.top>this.viewport.clientHeight)return;
      this.drag={id:event.pointerId,x:event.clientX,y:event.clientY,left:this.viewport.scrollLeft,top:this.viewport.scrollTop};
      this.viewport.setPointerCapture(event.pointerId);this.viewport.classList.add('dragging');event.preventDefault();
    });
    this.viewport.addEventListener('pointermove', event => {
      if(this.drag?.id!==event.pointerId)return;
      this.viewport.scrollLeft=this.drag.left-(event.clientX-this.drag.x);
      this.viewport.scrollTop=this.drag.top-(event.clientY-this.drag.y);
    });
    const end=()=>{this.drag=null;this.viewport.classList.remove('dragging');};
    this.viewport.addEventListener('pointerup',end);
    this.viewport.addEventListener('pointercancel',end);
    this.viewport.addEventListener('lostpointercapture',end);
    this.viewport.addEventListener('keydown', event=>{
      if(event.key==='+' || event.key==='='){event.preventDefault();this.setZoom(this.zoom*1.25);}
      if(event.key==='-'){event.preventDefault();this.setZoom(this.zoom/1.25);}
      if(event.key==='0'){event.preventDefault();this.setZoom(1);}
    });
    this.resizeObserver=new ResizeObserver(()=>{if(this.ready)this.resizeImage();});
  }

  connectedCallback(){this.resizeObserver.observe(this.viewport);}
  disconnectedCallback(){this.resizeObserver.disconnect();this.clear();}

  resizeImage(){
    const width=Math.max(1,this.viewport.clientWidth)*this.zoom;
    this.image.style.width=width+'px';
    // Altura proporcional explícita: mantém a mesma ampliação nos dois eixos.
    this.image.style.height=(width*this.aspect)+'px';
  }

  setZoom(value, x=this.viewport.clientWidth/2, y=this.viewport.clientHeight/2){
    if(!this.ready)return;
    const old=this.zoom;this.zoom=Math.min(16,Math.max(1,value));
    const ratio=this.zoom/old;
    const left=(this.viewport.scrollLeft+x)*ratio-x;
    const top=(this.viewport.scrollTop+y)*ratio-y;
    this.resizeImage();this.viewport.scrollLeft=left;this.viewport.scrollTop=top;
    this.output.value=Math.round(this.zoom*100)+'%';
    this.dispatchEvent(new CustomEvent('ecg-zoom',{detail:{zoom:this.zoom}}));
  }

  async load(blob){
    if(!(blob instanceof Blob) || blob.type.split(';')[0]!=='image/svg+xml')throw new Error('O visualizador exige um Blob image/svg+xml da API.');
    this.clear();const id=this.loadId;const url=URL.createObjectURL(blob);this.url=url;
    const probe=new Image();
    try{
      await new Promise((resolve,reject)=>{probe.onload=resolve;probe.onerror=()=>reject(new Error('SVG inválido ou bloqueado pela política de conteúdo.'));probe.src=url;});
    }catch(error){if(id!==this.loadId)return;this.clear();throw error;}
    if(id!==this.loadId)return; // Evita que uma resposta antiga substitua o exame atual.
    const documentSvg=new DOMParser().parseFromString(await blob.text(),'image/svg+xml');
    if(id!==this.loadId)return;
    const box=documentSvg.documentElement.getAttribute('viewBox')?.trim().split(/[\s,]+/).map(Number);
    if(!box||box.length!==4||!box.every(Number.isFinite)||box[2]<=0||box[3]<=0){this.clear();throw new Error('SVG não possui viewBox válido.');}
    this.aspect=box[3]/box[2];
    this.image.src=url;this.image.hidden=false;this.shadowRoot.querySelector('.empty').hidden=true;
    this.ready=true;this.zoom=1;
    this.shadowRoot.querySelectorAll('button').forEach(b=>b.disabled=false);
    this.resizeImage();this.viewport.scrollTo(0,0);this.output.value='100%';
  }

  clear(){
    this.loadId++;this.ready=false;this.zoom=1;this.output.value='100%';
    this.image.hidden=true;this.image.removeAttribute('src');
    this.shadowRoot.querySelector('.empty').hidden=false;
    this.shadowRoot.querySelectorAll('button').forEach(b=>b.disabled=true);
    if(this.url)URL.revokeObjectURL(this.url);this.url=null;
  }
}
if(!customElements.get('ecg-viewer'))customElements.define('ecg-viewer',EcgViewer);
