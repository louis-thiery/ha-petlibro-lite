var Tt=Object.defineProperty;var Rt=Object.getOwnPropertyDescriptor;var v=(n,t,e,i)=>{for(var s=i>1?void 0:i?Rt(t,e):t,o=n.length-1,r;o>=0;o--)(r=n[o])&&(s=(i?r(t,e,s):r(s))||s);return i&&s&&Tt(t,e,s),s};var W=globalThis,B=W.ShadowRoot&&(W.ShadyCSS===void 0||W.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,Z=Symbol(),dt=new WeakMap,R=class{constructor(t,e,i){if(this._$cssResult$=!0,i!==Z)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o,e=this.t;if(B&&t===void 0){let i=e!==void 0&&e.length===1;i&&(t=dt.get(e)),t===void 0&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),i&&dt.set(e,t))}return t}toString(){return this.cssText}},pt=n=>new R(typeof n=="string"?n:n+"",void 0,Z),Q=(n,...t)=>{let e=n.length===1?n[0]:t.reduce((i,s,o)=>i+(r=>{if(r._$cssResult$===!0)return r.cssText;if(typeof r=="number")return r;throw Error("Value passed to 'css' function must be a 'css' function result: "+r+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(s)+n[o+1],n[0]);return new R(e,n,Z)},ht=(n,t)=>{if(B)n.adoptedStyleSheets=t.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let e of t){let i=document.createElement("style"),s=W.litNonce;s!==void 0&&i.setAttribute("nonce",s),i.textContent=e.cssText,n.appendChild(i)}},tt=B?n=>n:n=>n instanceof CSSStyleSheet?(t=>{let e="";for(let i of t.cssRules)e+=i.cssText;return pt(e)})(n):n;var{is:Nt,defineProperty:zt,getOwnPropertyDescriptor:Ot,getOwnPropertyNames:Ut,getOwnPropertySymbols:Ht,getPrototypeOf:Lt}=Object,$=globalThis,ut=$.trustedTypes,jt=ut?ut.emptyScript:"",It=$.reactiveElementPolyfillSupport,N=(n,t)=>n,z={toAttribute(n,t){switch(t){case Boolean:n=n?jt:null;break;case Object:case Array:n=n==null?n:JSON.stringify(n)}return n},fromAttribute(n,t){let e=n;switch(t){case Boolean:e=n!==null;break;case Number:e=n===null?null:Number(n);break;case Object:case Array:try{e=JSON.parse(n)}catch{e=null}}return e}},F=(n,t)=>!Nt(n,t),ft={attribute:!0,type:String,converter:z,reflect:!1,useDefault:!1,hasChanged:F};Symbol.metadata??(Symbol.metadata=Symbol("metadata")),$.litPropertyMetadata??($.litPropertyMetadata=new WeakMap);var y=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??(this.l=[])).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=ft){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){let i=Symbol(),s=this.getPropertyDescriptor(t,i,e);s!==void 0&&zt(this.prototype,t,s)}}static getPropertyDescriptor(t,e,i){let{get:s,set:o}=Ot(this.prototype,t)??{get(){return this[e]},set(r){this[e]=r}};return{get:s,set(r){let a=s?.call(this);o?.call(this,r),this.requestUpdate(t,a,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??ft}static _$Ei(){if(this.hasOwnProperty(N("elementProperties")))return;let t=Lt(this);t.finalize(),t.l!==void 0&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(N("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(N("properties"))){let e=this.properties,i=[...Ut(e),...Ht(e)];for(let s of i)this.createProperty(s,e[s])}let t=this[Symbol.metadata];if(t!==null){let e=litPropertyMetadata.get(t);if(e!==void 0)for(let[i,s]of e)this.elementProperties.set(i,s)}this._$Eh=new Map;for(let[e,i]of this.elementProperties){let s=this._$Eu(e,i);s!==void 0&&this._$Eh.set(s,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){let e=[];if(Array.isArray(t)){let i=new Set(t.flat(1/0).reverse());for(let s of i)e.unshift(tt(s))}else t!==void 0&&e.push(tt(t));return e}static _$Eu(t,e){let i=e.attribute;return i===!1?void 0:typeof i=="string"?i:typeof t=="string"?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??(this._$EO=new Set)).add(t),this.renderRoot!==void 0&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){let t=new Map,e=this.constructor.elementProperties;for(let i of e.keys())this.hasOwnProperty(i)&&(t.set(i,this[i]),delete this[i]);t.size>0&&(this._$Ep=t)}createRenderRoot(){let t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return ht(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??(this.renderRoot=this.createRenderRoot()),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,i){this._$AK(t,i)}_$ET(t,e){let i=this.constructor.elementProperties.get(t),s=this.constructor._$Eu(t,i);if(s!==void 0&&i.reflect===!0){let o=(i.converter?.toAttribute!==void 0?i.converter:z).toAttribute(e,i.type);this._$Em=t,o==null?this.removeAttribute(s):this.setAttribute(s,o),this._$Em=null}}_$AK(t,e){let i=this.constructor,s=i._$Eh.get(t);if(s!==void 0&&this._$Em!==s){let o=i.getPropertyOptions(s),r=typeof o.converter=="function"?{fromAttribute:o.converter}:o.converter?.fromAttribute!==void 0?o.converter:z;this._$Em=s;let a=r.fromAttribute(e,o.type);this[s]=a??this._$Ej?.get(s)??a,this._$Em=null}}requestUpdate(t,e,i,s=!1,o){if(t!==void 0){let r=this.constructor;if(s===!1&&(o=this[t]),i??(i=r.getPropertyOptions(t)),!((i.hasChanged??F)(o,e)||i.useDefault&&i.reflect&&o===this._$Ej?.get(t)&&!this.hasAttribute(r._$Eu(t,i))))return;this.C(t,e,i)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(t,e,{useDefault:i,reflect:s,wrapped:o},r){i&&!(this._$Ej??(this._$Ej=new Map)).has(t)&&(this._$Ej.set(t,r??e??this[t]),o!==!0||r!==void 0)||(this._$AL.has(t)||(this.hasUpdated||i||(e=void 0),this._$AL.set(t,e)),s===!0&&this._$Em!==t&&(this._$Eq??(this._$Eq=new Set)).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let t=this.scheduleUpdate();return t!=null&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??(this.renderRoot=this.createRenderRoot()),this._$Ep){for(let[s,o]of this._$Ep)this[s]=o;this._$Ep=void 0}let i=this.constructor.elementProperties;if(i.size>0)for(let[s,o]of i){let{wrapped:r}=o,a=this[s];r!==!0||this._$AL.has(s)||a===void 0||this.C(s,void 0,o,a)}}let t=!1,e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(i=>i.hostUpdate?.()),this.update(e)):this._$EM()}catch(i){throw t=!1,this._$EM(),i}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&(this._$Eq=this._$Eq.forEach(e=>this._$ET(e,this[e]))),this._$EM()}updated(t){}firstUpdated(t){}};y.elementStyles=[],y.shadowRootOptions={mode:"open"},y[N("elementProperties")]=new Map,y[N("finalized")]=new Map,It?.({ReactiveElement:y}),($.reactiveElementVersions??($.reactiveElementVersions=[])).push("2.1.2");var U=globalThis,gt=n=>n,V=U.trustedTypes,mt=V?V.createPolicy("lit-html",{createHTML:n=>n}):void 0,$t="$lit$",w=`lit$${Math.random().toFixed(9).slice(2)}$`,wt="?"+w,qt=`<${wt}>`,E=document,H=()=>E.createComment(""),L=n=>n===null||typeof n!="object"&&typeof n!="function",at=Array.isArray,Wt=n=>at(n)||typeof n?.[Symbol.iterator]=="function",et=`[ 	
\f\r]`,O=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,bt=/-->/g,vt=/>/g,A=RegExp(`>|${et}(?:([^\\s"'>=/]+)(${et}*=${et}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),_t=/'/g,xt=/"/g,St=/^(?:script|style|textarea|title)$/i,lt=n=>(t,...e)=>({_$litType$:n,strings:t,values:e}),d=lt(1),le=lt(2),ce=lt(3),C=Symbol.for("lit-noChange"),c=Symbol.for("lit-nothing"),yt=new WeakMap,k=E.createTreeWalker(E,129);function At(n,t){if(!at(n)||!n.hasOwnProperty("raw"))throw Error("invalid template strings array");return mt!==void 0?mt.createHTML(t):t}var Bt=(n,t)=>{let e=n.length-1,i=[],s,o=t===2?"<svg>":t===3?"<math>":"",r=O;for(let a=0;a<e;a++){let l=n[a],p,u,h=-1,g=0;for(;g<l.length&&(r.lastIndex=g,u=r.exec(l),u!==null);)g=r.lastIndex,r===O?u[1]==="!--"?r=bt:u[1]!==void 0?r=vt:u[2]!==void 0?(St.test(u[2])&&(s=RegExp("</"+u[2],"g")),r=A):u[3]!==void 0&&(r=A):r===A?u[0]===">"?(r=s??O,h=-1):u[1]===void 0?h=-2:(h=r.lastIndex-u[2].length,p=u[1],r=u[3]===void 0?A:u[3]==='"'?xt:_t):r===xt||r===_t?r=A:r===bt||r===vt?r=O:(r=A,s=void 0);let b=r===A&&n[a+1].startsWith("/>")?" ":"";o+=r===O?l+qt:h>=0?(i.push(p),l.slice(0,h)+$t+l.slice(h)+w+b):l+w+(h===-2?a:b)}return[At(n,o+(n[e]||"<?>")+(t===2?"</svg>":t===3?"</math>":"")),i]},j=class n{constructor({strings:t,_$litType$:e},i){let s;this.parts=[];let o=0,r=0,a=t.length-1,l=this.parts,[p,u]=Bt(t,e);if(this.el=n.createElement(p,i),k.currentNode=this.el.content,e===2||e===3){let h=this.el.content.firstChild;h.replaceWith(...h.childNodes)}for(;(s=k.nextNode())!==null&&l.length<a;){if(s.nodeType===1){if(s.hasAttributes())for(let h of s.getAttributeNames())if(h.endsWith($t)){let g=u[r++],b=s.getAttribute(h).split(w),f=/([.?@])?(.*)/.exec(g);l.push({type:1,index:o,name:f[2],strings:b,ctor:f[1]==="."?st:f[1]==="?"?ot:f[1]==="@"?nt:M}),s.removeAttribute(h)}else h.startsWith(w)&&(l.push({type:6,index:o}),s.removeAttribute(h));if(St.test(s.tagName)){let h=s.textContent.split(w),g=h.length-1;if(g>0){s.textContent=V?V.emptyScript:"";for(let b=0;b<g;b++)s.append(h[b],H()),k.nextNode(),l.push({type:2,index:++o});s.append(h[g],H())}}}else if(s.nodeType===8)if(s.data===wt)l.push({type:2,index:o});else{let h=-1;for(;(h=s.data.indexOf(w,h+1))!==-1;)l.push({type:7,index:o}),h+=w.length-1}o++}}static createElement(t,e){let i=E.createElement("template");return i.innerHTML=t,i}};function P(n,t,e=n,i){if(t===C)return t;let s=i!==void 0?e._$Co?.[i]:e._$Cl,o=L(t)?void 0:t._$litDirective$;return s?.constructor!==o&&(s?._$AO?.(!1),o===void 0?s=void 0:(s=new o(n),s._$AT(n,e,i)),i!==void 0?(e._$Co??(e._$Co=[]))[i]=s:e._$Cl=s),s!==void 0&&(t=P(n,s._$AS(n,t.values),s,i)),t}var it=class{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){let{el:{content:e},parts:i}=this._$AD,s=(t?.creationScope??E).importNode(e,!0);k.currentNode=s;let o=k.nextNode(),r=0,a=0,l=i[0];for(;l!==void 0;){if(r===l.index){let p;l.type===2?p=new I(o,o.nextSibling,this,t):l.type===1?p=new l.ctor(o,l.name,l.strings,this,t):l.type===6&&(p=new rt(o,this,t)),this._$AV.push(p),l=i[++a]}r!==l?.index&&(o=k.nextNode(),r++)}return k.currentNode=E,s}p(t){let e=0;for(let i of this._$AV)i!==void 0&&(i.strings!==void 0?(i._$AI(t,i,e),e+=i.strings.length-2):i._$AI(t[e])),e++}},I=class n{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,i,s){this.type=2,this._$AH=c,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=i,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode,e=this._$AM;return e!==void 0&&t?.nodeType===11&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=P(this,t,e),L(t)?t===c||t==null||t===""?(this._$AH!==c&&this._$AR(),this._$AH=c):t!==this._$AH&&t!==C&&this._(t):t._$litType$!==void 0?this.$(t):t.nodeType!==void 0?this.T(t):Wt(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==c&&L(this._$AH)?this._$AA.nextSibling.data=t:this.T(E.createTextNode(t)),this._$AH=t}$(t){let{values:e,_$litType$:i}=t,s=typeof i=="number"?this._$AC(t):(i.el===void 0&&(i.el=j.createElement(At(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===s)this._$AH.p(e);else{let o=new it(s,this),r=o.u(this.options);o.p(e),this.T(r),this._$AH=o}}_$AC(t){let e=yt.get(t.strings);return e===void 0&&yt.set(t.strings,e=new j(t)),e}k(t){at(this._$AH)||(this._$AH=[],this._$AR());let e=this._$AH,i,s=0;for(let o of t)s===e.length?e.push(i=new n(this.O(H()),this.O(H()),this,this.options)):i=e[s],i._$AI(o),s++;s<e.length&&(this._$AR(i&&i._$AB.nextSibling,s),e.length=s)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){let i=gt(t).nextSibling;gt(t).remove(),t=i}}setConnected(t){this._$AM===void 0&&(this._$Cv=t,this._$AP?.(t))}},M=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,i,s,o){this.type=1,this._$AH=c,this._$AN=void 0,this.element=t,this.name=e,this._$AM=s,this.options=o,i.length>2||i[0]!==""||i[1]!==""?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=c}_$AI(t,e=this,i,s){let o=this.strings,r=!1;if(o===void 0)t=P(this,t,e,0),r=!L(t)||t!==this._$AH&&t!==C,r&&(this._$AH=t);else{let a=t,l,p;for(t=o[0],l=0;l<o.length-1;l++)p=P(this,a[i+l],e,l),p===C&&(p=this._$AH[l]),r||(r=!L(p)||p!==this._$AH[l]),p===c?t=c:t!==c&&(t+=(p??"")+o[l+1]),this._$AH[l]=p}r&&!s&&this.j(t)}j(t){t===c?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}},st=class extends M{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===c?void 0:t}},ot=class extends M{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==c)}},nt=class extends M{constructor(t,e,i,s,o){super(t,e,i,s,o),this.type=5}_$AI(t,e=this){if((t=P(this,t,e,0)??c)===C)return;let i=this._$AH,s=t===c&&i!==c||t.capture!==i.capture||t.once!==i.once||t.passive!==i.passive,o=t!==c&&(i===c||s);s&&this.element.removeEventListener(this.name,this,i),o&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}},rt=class{constructor(t,e,i){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(t){P(this,t)}};var Ft=U.litHtmlPolyfillSupport;Ft?.(j,I),(U.litHtmlVersions??(U.litHtmlVersions=[])).push("3.3.2");var kt=(n,t,e)=>{let i=e?.renderBefore??t,s=i._$litPart$;if(s===void 0){let o=e?.renderBefore??null;i._$litPart$=s=new I(t.insertBefore(H(),o),o,void 0,e??{})}return s._$AI(n),s};var q=globalThis,S=class extends y{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){var e;let t=super.createRenderRoot();return(e=this.renderOptions).renderBefore??(e.renderBefore=t.firstChild),t}update(t){let e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=kt(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return C}};S._$litElement$=!0,S.finalized=!0,q.litElementHydrateSupport?.({LitElement:S});var Vt=q.litElementPolyfillSupport;Vt?.({LitElement:S});(q.litElementVersions??(q.litElementVersions=[])).push("4.2.2");var Et=n=>(t,e)=>{e!==void 0?e.addInitializer(()=>{customElements.define(n,t)}):customElements.define(n,t)};var Gt={attribute:!0,type:String,converter:z,reflect:!1,hasChanged:F},Kt=(n=Gt,t,e)=>{let{kind:i,metadata:s}=e,o=globalThis.litPropertyMetadata.get(s);if(o===void 0&&globalThis.litPropertyMetadata.set(s,o=new Map),i==="setter"&&((n=Object.create(n)).wrapped=!0),o.set(e.name,n),i==="accessor"){let{name:r}=e;return{set(a){let l=t.get.call(this);t.set.call(this,a),this.requestUpdate(r,l,n,!0,a)},init(a){return a!==void 0&&this.C(r,void 0,n,a),a}}}if(i==="setter"){let{name:r}=e;return function(a){let l=this[r];t.call(this,a),this.requestUpdate(r,l,n,!0,a)}}throw Error("Unsupported decorator location: "+i)};function G(n){return(t,e)=>typeof e=="object"?Kt(n,t,e):((i,s,o)=>{let r=s.hasOwnProperty(o);return s.constructor.createProperty(o,i),r?Object.getOwnPropertyDescriptor(s,o):void 0})(n,t,e)}function x(n){return G({...n,state:!0,attribute:!1})}var Yt={2:"Outlet blocked"},Jt=new Set(["ok","0","none","unknown","unavailable"]);var D=["mon","tue","wed","thu","fri","sat","sun"],Xt={mon:"M",tue:"T",wed:"W",thu:"T",fri:"F",sat:"S",sun:"S"};function Zt(n){let t=new Set(n.map(s=>s.toLowerCase()));if(D.every(s=>t.has(s)))return"Every day";let e=D.slice(0,5),i=["sat","sun"];return e.every(s=>t.has(s))&&i.every(s=>!t.has(s))?"Weekdays":i.every(s=>t.has(s))&&e.every(s=>!t.has(s))?"Weekends":D.filter(s=>t.has(s)).map(s=>s[0].toUpperCase()+s.slice(1)).join(", ")}function Qt(n,t){return`${String(n).padStart(2,"0")}:${String(t).padStart(2,"0")}`}function Ct(n,t){let e=n>=12?"PM":"AM",i=n%12||12;return t===0?`${i} ${e}`:`${i}:${String(t).padStart(2,"0")} ${e}`}function te(n){let t=Date.parse(n);if(Number.isNaN(t))return"";let e=new Date(t),i=new Date,s=new Date(i.getFullYear(),i.getMonth(),i.getDate()),o=Math.floor((new Date(e.getFullYear(),e.getMonth(),e.getDate()).getTime()-s.getTime())/864e5),r=Ct(e.getHours(),e.getMinutes());return o===0?`Today, ${r}`:o===1?`Tomorrow, ${r}`:`${e.toLocaleDateString(void 0,{weekday:"short"})}, ${r}`}var Y=50,ee=new Set(["signaling","ice","auth","waiting_frame"]),ie={signaling:"Connecting\u2026",ice:"Establishing link\u2026",auth:"Authorizing\u2026",waiting_frame:"Waiting for first frame\u2026",streaming:"Live",error:"Camera error",idle:""},m=class extends S{constructor(){super(...arguments);this._pendingPortions=null;this._customPortionsMode=!1;this._customPortionsValue=4;this._dialogMode=null;this._editing=null;this._editDraft=null;this._savingSchedule=!1;this._optimisticSlots=null;this._lastSeenSlots=null;this._dialogRefreshTimer=null}setConfig(e){if(!e?.feed_number)throw new Error("petlibro-feeder-card: 'feed_number' is required");this._config=e}getCardSize(){return this._config?.camera_entity?5:2}static getStubConfig(){return{name:"PetLibro",feed_number:"",portions:[1,2]}}_s(e){if(!(!e||!this.hass))return this.hass.states[e]}_relativeTime(e){if(e==null)return"\u2014";let i=typeof e=="number"?e*1e3:Date.parse(e);if(Number.isNaN(i))return"\u2014";let s=(Date.now()-i)/1e3;return s<60?"just now":s<3600?`${Math.floor(s/60)}m ago`:s<86400?`${Math.floor(s/3600)}h ago`:`${Math.floor(s/86400)}d ago`}async _feed(e){if(!this.hass||!this._config||this._pendingPortions!==null)return;let i=Math.max(1,Math.min(Y,Math.floor(e)));this._pendingPortions=i,this._customPortionsMode=!1;try{await this.hass.callService("number","set_value",{value:i},{entity_id:this._config.feed_number})}finally{setTimeout(()=>{this._pendingPortions=null},2500)}}_openCustomPortions(){this._customPortionsMode=!0}_cancelCustomPortions(){this._customPortionsMode=!1}_onCustomPortionsInput(e){let i=e.target,s=Number(i.value);Number.isFinite(s)&&(this._customPortionsValue=Math.max(1,Math.min(Y,Math.floor(s))))}_submitCustomPortions(){this._feed(this._customPortionsValue)}_openMore(e){if(!e)return;let i=new Event("hass-more-info",{bubbles:!0,composed:!0});i.detail={entityId:e},this.dispatchEvent(i)}_renderGlance(){let e=this._s(this._config?.next_feed_sensor),i=this._s(this._config?.portions_today_sensor);if(!e&&!i)return c;let s=e&&e.state!=="unknown"&&e.state!=="unavailable"?te(e.state):"",o=Number(e?.attributes?.portions??0),r=i?.state,a=r&&r!=="unknown"&&r!=="unavailable"?Number(r):NaN;return d`
      <div class="glance">
        ${e?d`
              <div
                class="glance-item"
                @click=${()=>this._openMore(this._config.next_feed_sensor)}
                role="button"
                tabindex="0"
              >
                <ha-icon icon="mdi:calendar-clock"></ha-icon>
                <div class="glance-text">
                  <div class="glance-label">Next feed</div>
                  <div class="glance-value">
                    ${s||"\u2014"}${o>0?d` · <span class="portions"
                            >${o}p</span
                          >`:c}
                  </div>
                </div>
              </div>
            `:c}
        ${i?d`
              <div
                class="glance-item"
                @click=${()=>this._openMore(this._config.portions_today_sensor)}
                role="button"
                tabindex="0"
              >
                <ha-icon icon="mdi:counter"></ha-icon>
                <div class="glance-text">
                  <div class="glance-label">Today</div>
                  <div class="glance-value">
                    ${Number.isFinite(a)?d`${a}
                          <span class="glance-unit"
                            >portion${a===1?"":"s"}</span
                          >`:"\u2014"}
                  </div>
                </div>
              </div>
            `:c}
      </div>
    `}_openDialog(e){this._dialogMode=e,this._refreshForDialog(e),this._dialogRefreshTimer!==null&&window.clearInterval(this._dialogRefreshTimer),this._dialogRefreshTimer=window.setInterval(()=>{this._refreshForDialog(e)},3e3)}_refreshForDialog(e){if(!this.hass)return;let i=this._config?.device_id,s=i?{device_id:i}:{},o=["refresh_state"];for(let r of o)this.hass.callService("petlibro_lite",r,s).catch(()=>{})}_closeDialog(){this._dialogMode=null,this._editing=null,this._editDraft=null,this._optimisticSlots=null,this._dialogRefreshTimer!==null&&(window.clearInterval(this._dialogRefreshTimer),this._dialogRefreshTimer=null)}disconnectedCallback(){super.disconnectedCallback(),this._dialogRefreshTimer!==null&&(window.clearInterval(this._dialogRefreshTimer),this._dialogRefreshTimer=null)}_latestFed(e,i){let s=f=>f&&f.state!=="unknown"&&f.state!=="unavailable"?f.state:void 0,o=s(e),r=s(i);if(!o&&!r)return;let a=o?Date.parse(o):0,l=r?Date.parse(r):0,p=a>=l&&o,u=p?o:r,g=(p?e:i)?.attributes?.portions,b=typeof g=="number"?g:typeof g=="string"&&Number(g)||void 0;return{iso:u,portions:b,kind:p?"manual":"scheduled"}}_logEntries(){let i=this._s(this._config?.feed_log_sensor)?.attributes?.entries;return Array.isArray(i)?i:[]}_schedules(){if(this._optimisticSlots!==null)return this._optimisticSlots;let i=this._s(this._config?.schedules_sensor)?.attributes?.slots;return Array.isArray(i)?(this._lastSeenSlots=i,i.slice().sort((s,o)=>s.hour*60+s.minute-(o.hour*60+o.minute))):(this._lastSeenSlots??[]).slice().sort((s,o)=>s.hour*60+s.minute-(o.hour*60+o.minute))}_slotsSignature(e){return e.slice().sort((i,s)=>i.hour*60+i.minute-(s.hour*60+s.minute)).map(i=>[i.hour,i.minute,i.portions,i.enabled?1:0,i.days.slice().sort().join(",")].join(":")).join("|")}updated(e){if(super.updated?.(e),this._optimisticSlots!==null&&e.has("hass")){let s=this._s(this._config?.schedules_sensor)?.attributes?.slots;Array.isArray(s)&&this._slotsSignature(s)===this._slotsSignature(this._optimisticSlots)&&(this._optimisticSlots=null)}}async _writeSchedules(e){if(!(!this.hass||!this._config?.device_id)){this._optimisticSlots=e;try{await this.hass.callService("petlibro_lite","schedule_set_all",{device_id:this._config.device_id,slots:e})}catch(i){throw this._optimisticSlots=null,i}}}async _toggleSlot(e){let s=this._schedules().map((o,r)=>r===e?{...o,enabled:!o.enabled}:o);await this._writeSchedules(s)}async _deleteSlot(e){let s=this._schedules().filter((o,r)=>r!==e);await this._writeSchedules(s)}_startAdd(){this._editing={mode:"add"},this._editDraft={hour:8,minute:0,portions:1,enabled:!0,days:[...D]}}_startEdit(e){let i=this._schedules()[e];i&&(this._editing={mode:"edit",index:e},this._editDraft={...i,days:[...i.days]})}async _saveEdit(){if(!(!this._editing||!this._editDraft||this._savingSchedule)){this._savingSchedule=!0;try{let e=this._schedules(),i;if(this._editing.mode==="add")i=[...e,this._editDraft];else{let s=this._editing.index;i=e.map((o,r)=>r===s?this._editDraft:o)}await this._writeSchedules(i),this._editing=null,this._editDraft=null}finally{this._savingSchedule=!1}}}_updateDraft(e){this._editDraft&&(this._editDraft={...this._editDraft,...e})}_toggleDraftDay(e){if(!this._editDraft)return;let i=new Set(this._editDraft.days);i.has(e)?i.delete(e):i.add(e),this._editDraft={...this._editDraft,days:D.filter(s=>i.has(s))}}render(){if(!this._config||!this.hass)return c;let e=this._s(this._config.state_sensor),i=this._s(this._config.food_level_sensor),s=this._s(this._config.last_manual_sensor),o=this._s(this._config.last_scheduled_sensor),r=this._s(this._config.warning_sensor),a=this._s(this._config.camera_entity),l=this._config.name??"PetLibro Feeder",p=e?.state==="feeding",u=e?.state==="unavailable",h=i?.state??"",g=r?.state??"ok",b=!Jt.has(g),f=null;u?f={label:"offline",icon:"mdi:cloud-off-outline",sev:"error"}:h==="empty"?f={label:"out of food",icon:"mdi:bowl-outline",sev:"error"}:b?f={label:g.replace(/_/g," "),icon:"mdi:alert-circle-outline",sev:g==="outlet_blocked"?"error":"warn"}:h==="low"&&(f={label:"food low",icon:"mdi:bowl-outline",sev:"warn"});let T=this._latestFed(s,o),Pt=this._config.portions??[1,2],ct=a?.attributes?a.attributes.entity_picture:void 0,J=a?.attributes?.stream_state,Mt=!!J&&ee.has(J),Dt=!!(this._config.feed_log_sensor||this._config.schedules_sensor);return d`
      <ha-card>
        ${ct?d`
              <div
                class="camera-thumb"
                @click=${()=>this._openMore(this._config.camera_entity)}
                role="button"
                tabindex="0"
              >
                <img src=${ct} alt="feeder camera" />
                ${Mt?d`
                      <div class="connecting-overlay">
                        <div class="spinner"></div>
                        <div class="connecting-text">
                          ${ie[J]??"Connecting\u2026"}
                        </div>
                      </div>
                    `:p?d`<div class="feeding-pill">
                        <ha-icon icon="mdi:paw"></ha-icon>Feeding
                      </div>`:c}
              </div>
            `:c}
        <div class="header">
          <div class="name">
            <ha-icon icon="mdi:cat"></ha-icon>
            <span>${l}</span>
          </div>
          ${f?d`
                <div
                  class="badge ${f.sev}"
                  @click=${()=>this._openMore(f.label==="offline"?this._config.state_sensor:f.label.startsWith("food")||f.label==="out of food"?this._config.food_level_sensor:this._config.warning_sensor)}
                >
                  <ha-icon icon=${f.icon}></ha-icon>
                  <span>${f.label}</span>
                </div>
              `:c}
        </div>
        <div class="status-card ${p?"feeding":""}">
          <ha-icon
            class="status-icon"
            icon=${p?"mdi:silverware-clean":"mdi:paw"}
          ></ha-icon>
          <div class="status-text">
            <div class="status-title">
              ${p?"Dispensing now\u2026":"Ready"}
            </div>
            <div class="status-sub">
              ${p?"Motor is running":T?d`Last fed
                      ${this._relativeTime(T.iso)}${T.portions?d` · <span class="portions"
                              >${T.portions}p</span
                            >`:c}
                      · ${T.kind}`:"No feeds recorded yet"}
            </div>
          </div>
        </div>
        ${this._renderGlance()}
        <div class="manual-feed">
          <div class="manual-feed-label">Manual Feed</div>
          ${this._customPortionsMode?d`
                <div class="feed-row custom-portions">
                  <select
                    class="portion-select"
                    .value=${String(this._customPortionsValue)}
                    @change=${this._onCustomPortionsInput}
                  >
                    ${Array.from({length:Y},(_,X)=>X+1).map(_=>d`
                        <option
                          value=${_}
                          ?selected=${_===this._customPortionsValue}
                        >
                          ${_} portion${_===1?"":"s"}
                        </option>
                      `)}
                  </select>
                  <button
                    class="pf-btn pf-btn-primary feed-submit"
                    ?disabled=${this._pendingPortions!==null||u}
                    @click=${()=>this._submitCustomPortions()}
                  >
                    ${this._pendingPortions!==null?"Feeding\u2026":"Feed"}
                  </button>
                  <button
                    class="pf-btn pf-btn-outline portion-cancel"
                    @click=${()=>this._cancelCustomPortions()}
                    title="Cancel"
                  >
                    <ha-icon icon="mdi:close"></ha-icon>
                  </button>
                </div>
              `:d`
                <div class="feed-row">
                  ${Pt.map((_,X)=>d`
                      <button
                        class="pf-btn ${X===0?"pf-btn-primary":"pf-btn-outline"} ${this._pendingPortions===_?"pending":""}"
                        ?disabled=${this._pendingPortions!==null||u}
                        @click=${()=>this._feed(_)}
                      >
                        ${this._pendingPortions===_?"Feeding\u2026":`${_} portion${_===1?"":"s"}`}
                      </button>
                    `)}
                  <button
                    class="pf-btn pf-btn-outline portion-more"
                    ?disabled=${this._pendingPortions!==null||u}
                    @click=${()=>this._openCustomPortions()}
                    title="Custom portions (1–${Y})"
                  >
                    &hellip;
                  </button>
                </div>
              `}
          <div class="manual-feed-hint">
            1 portion ≈ 10g · feeder rate-limits rapid requests
          </div>
        </div>
        ${Dt?d`
              <div class="secondary-actions">
                ${this._config.feed_log_sensor?d`
                      <button
                        class="secondary-btn"
                        @click=${()=>this._openDialog("log")}
                      >
                        <ha-icon icon="mdi:history"></ha-icon>
                        <span>Activity</span>
                      </button>
                    `:c}
                ${this._config.schedules_sensor?d`
                      <button
                        class="secondary-btn"
                        @click=${()=>this._openDialog("schedules")}
                      >
                        <ha-icon icon="mdi:clock-outline"></ha-icon>
                        <span>Schedules</span>
                      </button>
                    `:c}
              </div>
            `:c}
      </ha-card>
      ${this._dialogMode?this._renderDialog():c}
    `}_renderDialog(){let e=this._config?.name??"PetLibro Feeder",i=this._dialogMode,s=i==="schedules"?"mdi:clock-outline":"mdi:history",o=i==="schedules"?this._editing?this._editing.mode==="add"?"Add schedule":"Edit schedule":"Schedules":"Activity";return d`
      <div
        class="dialog-scrim"
        @click=${r=>{r.target===r.currentTarget&&this._closeDialog()}}
      >
        <div class="dialog">
          <div class="dialog-header">
            <div class="dialog-title">
              <ha-icon icon=${s}></ha-icon>
              <span>${o}</span>
              <span class="dialog-subtitle">${e}</span>
            </div>
            <button
              class="dialog-close"
              @click=${()=>this._closeDialog()}
              title="Close"
            >
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
          ${i==="schedules"?this._editing?this._renderEditor():this._renderSchedules(this._schedules(),!!this._config?.device_id):this._renderLog(this._logEntries())}
        </div>
      </div>
    `}_renderLog(e){let i=e.slice(0,25).map(s=>this._describeLogEntry(s));return d`
      <div class="section">
        ${e.length===0?d`<div class="empty">No recent feed events</div>`:d`
              <ul class="log">
                ${i.map(s=>d`
                    <li class=${s.severity}>
                      <ha-icon icon=${s.icon}></ha-icon>
                      <span class="log-primary">${s.label}</span>
                      <span class="log-time">${s.timeLabel}</span>
                    </li>
                  `)}
              </ul>
            `}
      </div>
    `}_describeLogEntry(e){let i=this._relativeTime(e.time);if(e.kind==="warning")return{icon:"mdi:alert-circle-outline",label:e.code!=null?Yt[e.code]??`Warning (code ${e.code})`:"Warning",severity:"warn",timeLabel:i};let s=e.portions??0;return s===0?{icon:"mdi:alert-circle-outline",label:"Feed attempt \u2014 0 dispensed",severity:"warn",timeLabel:i}:e.kind==="scheduled"?{icon:"mdi:clock-outline",label:`Scheduled feed \xB7 ${s}p`,severity:"scheduled",timeLabel:i}:{icon:"mdi:paw",label:`Fed manually \xB7 ${s}p`,severity:"feed",timeLabel:i}}_renderSchedules(e,i){return d`
      <div class="section">
        ${i?d`
              <div class="section-toolbar">
                <button
                  class="add-btn"
                  @click=${()=>this._startAdd()}
                  title="Add a scheduled feed"
                >
                  <ha-icon icon="mdi:plus"></ha-icon>Add schedule
                </button>
              </div>
            `:c}
        ${e.length===0?d`<div class="empty">No schedules configured</div>`:d`
              <ul class="schedules">
                ${e.map((s,o)=>d`
                    <li class=${s.enabled?"enabled":"disabled"}>
                      <div class="sched-time">${Ct(s.hour,s.minute)}</div>
                      <div class="sched-meta">
                        <div class="sched-days">${Zt(s.days)}</div>
                        <div class="sched-portions">
                          ${s.portions} portion${s.portions===1?"":"s"}
                        </div>
                      </div>
                      ${i?d`
                            <button
                              class="icon-btn"
                              title=${s.enabled?"Disable":"Enable"}
                              @click=${()=>this._toggleSlot(o)}
                            >
                              <ha-icon
                                icon=${s.enabled?"mdi:toggle-switch":"mdi:toggle-switch-off-outline"}
                              ></ha-icon>
                            </button>
                            <button
                              class="icon-btn"
                              title="Edit"
                              @click=${()=>this._startEdit(o)}
                            >
                              <ha-icon icon="mdi:pencil"></ha-icon>
                            </button>
                            <button
                              class="icon-btn danger"
                              title="Delete"
                              @click=${()=>this._deleteSlot(o)}
                            >
                              <ha-icon icon="mdi:trash-can-outline"></ha-icon>
                            </button>
                          `:c}
                    </li>
                  `)}
              </ul>
            `}
      </div>
    `}_renderEditor(){if(!this._editDraft)return d``;let e=this._editDraft,i=this._editing?.mode==="add",s=e.days.length>0&&e.portions>=1&&e.portions<=50&&!this._savingSchedule;return d`
      <div class="section editor">
        <div class="editor-row">
          <label>Time</label>
          <input
            class="time-input"
            type="time"
            .value=${Qt(e.hour,e.minute)}
            @change=${o=>{let[r,a]=o.target.value.split(":");this._updateDraft({hour:Number(r)||0,minute:Number(a)||0})}}
          />
        </div>
        <div class="editor-row">
          <label>Portions</label>
          <div class="stepper">
            <button
              class="icon-btn"
              @click=${()=>this._updateDraft({portions:Math.max(1,e.portions-1)})}
              ?disabled=${e.portions<=1}
            >
              <ha-icon icon="mdi:minus"></ha-icon>
            </button>
            <div class="stepper-value">${e.portions}</div>
            <button
              class="icon-btn"
              @click=${()=>this._updateDraft({portions:Math.min(50,e.portions+1)})}
              ?disabled=${e.portions>=50}
            >
              <ha-icon icon="mdi:plus"></ha-icon>
            </button>
          </div>
        </div>
        <div class="editor-row">
          <label>Days</label>
          <div class="day-chips">
            ${D.map((o,r)=>{let a=e.days.includes(o);return d`
                <button
                  class="day-chip ${a?"active":""}"
                  @click=${()=>this._toggleDraftDay(o)}
                  title=${o}
                >
                  ${Xt[o]}<sub>${r+1}</sub>
                </button>
              `})}
          </div>
        </div>
        <div class="editor-row">
          <label>Enabled</label>
          <button
            class="icon-btn big"
            @click=${()=>this._updateDraft({enabled:!e.enabled})}
          >
            <ha-icon
              icon=${e.enabled?"mdi:toggle-switch":"mdi:toggle-switch-off-outline"}
            ></ha-icon>
          </button>
        </div>
        <div class="editor-actions">
          <button
            class="btn ghost"
            @click=${()=>{this._editing=null,this._editDraft=null}}
          >
            Cancel
          </button>
          <button
            class="btn primary"
            ?disabled=${!s}
            @click=${()=>this._saveEdit()}
          >
            ${this._savingSchedule?"Saving\u2026":i?"Add":"Save"}
          </button>
        </div>
      </div>
    `}};m.styles=Q`
    :host {
      --petlibro-accent: var(--primary-color, #03a9f4);
      --petlibro-warn: var(--warning-color, #ff9800);
      --petlibro-error: var(--error-color, #e45353);
    }
    ha-card {
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .camera-thumb {
      margin: -14px -16px 4px;
      position: relative;
      cursor: pointer;
      background: var(--card-background-color, #000);
      overflow: hidden;
    }
    .camera-thumb img {
      display: block;
      width: 100%;
      height: auto;
      aspect-ratio: 16 / 9;
      object-fit: cover;
    }
    .connecting-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      background: rgba(0, 0, 0, 0.55);
      color: #fff;
      backdrop-filter: blur(4px);
    }
    .spinner {
      width: 28px;
      height: 28px;
      border: 3px solid rgba(255, 255, 255, 0.25);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.9s linear infinite;
    }
    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
    .connecting-text {
      font-size: 13px;
      font-weight: 500;
      letter-spacing: 0.02em;
    }
    .feeding-pill {
      position: absolute;
      top: 8px;
      left: 8px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 10px;
      font-size: 12px;
      font-weight: 500;
      background: rgba(0, 0, 0, 0.55);
      color: #fff;
      border-radius: 999px;
      backdrop-filter: blur(6px);
    }
    .feeding-pill ha-icon {
      --mdc-icon-size: 14px;
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .name {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 16px;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .name ha-icon {
      --mdc-icon-size: 20px;
      color: var(--petlibro-accent);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 10px;
      font-size: 12px;
      font-weight: 500;
      color: #fff;
      border-radius: 999px;
      cursor: pointer;
      white-space: nowrap;
    }
    .badge.warn {
      background: var(--petlibro-warn);
    }
    .badge.error {
      background: var(--petlibro-error);
    }
    .badge ha-icon {
      --mdc-icon-size: 14px;
    }
    /* Status card: mirror the React dashboard's status row.
       Muted background, icon left, title + subtitle stacked. */
    .status-card {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--divider-color, #d0d0d0) 30%, transparent);
    }
    .status-card .status-icon {
      --mdc-icon-size: 22px;
      color: var(--secondary-text-color);
      flex-shrink: 0;
    }
    .status-card.feeding .status-icon {
      color: var(--petlibro-accent);
      animation: pf-pulse 1.3s ease-in-out infinite;
    }
    @keyframes pf-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.45; }
    }
    .status-text {
      flex: 1;
      min-width: 0;
    }
    .status-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .status-sub {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-top: 1px;
    }
    /* Glance strip: compact "Next feed" / "Today" summary between the
       status card and Manual Feed section. Two-up grid that collapses
       gracefully when only one sensor is wired. */
    .glance {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
      gap: 8px;
    }
    .glance-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 10px;
      background: color-mix(in srgb, var(--divider-color, #d0d0d0) 18%, transparent);
      cursor: pointer;
      transition: background 0.15s ease;
    }
    .glance-item:hover {
      background: color-mix(in srgb, var(--divider-color, #d0d0d0) 32%, transparent);
    }
    .glance-item ha-icon {
      --mdc-icon-size: 18px;
      color: var(--secondary-text-color);
      flex-shrink: 0;
    }
    .glance-text {
      min-width: 0;
    }
    .glance-label {
      font-size: 11px;
      color: var(--secondary-text-color);
      text-transform: uppercase;
      letter-spacing: 0.4px;
    }
    .glance-value {
      font-size: 14px;
      color: var(--primary-text-color);
      font-weight: 500;
      margin-top: 2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .glance-value .portions {
      color: var(--petlibro-accent);
      font-weight: 600;
    }
    .glance-value .glance-unit {
      color: var(--secondary-text-color);
      font-size: 12px;
      font-weight: 400;
      margin-left: 2px;
    }
    .status-sub .portions {
      color: var(--primary-text-color);
      font-weight: 500;
    }
    /* Legacy .last-fed style kept for the dialog feed log. */
    .last-fed {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      color: var(--secondary-text-color);
    }
    .last-fed ha-icon {
      --mdc-icon-size: 15px;
      color: var(--petlibro-accent);
    }
    .last-fed .portions {
      color: var(--primary-text-color);
      font-weight: 500;
    }
    .last-fed .kind {
      margin-left: auto;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--secondary-text-color);
      opacity: 0.75;
    }
    .manual-feed {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .manual-feed-label {
      padding: 0 4px;
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .manual-feed-hint {
      padding: 0 4px;
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .feed-row {
      display: flex;
      gap: 8px;
    }
    .feed-row > .pf-btn {
      flex: 1;
      min-width: 0;
    }
    .secondary-actions {
      display: flex;
      gap: 8px;
      margin-top: 2px;
    }
    .secondary-btn {
      flex: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 10px;
      border: 1px solid var(--divider-color, #d0d0d0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      border-radius: 10px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition:
        background 0.15s,
        border-color 0.15s;
    }
    .secondary-btn:hover {
      background: var(--secondary-background-color, #f3f3f3);
      border-color: var(--petlibro-accent);
    }
    .secondary-btn ha-icon {
      --mdc-icon-size: 16px;
      color: var(--petlibro-accent);
    }
    /* shadcn-Button-flavored portion buttons: one primary, rest outline.
       Matches the React dashboard's Manual Feed row — a single fluent
       label per button ("1 portion", "2 portions", …), not count/unit
       stacked. Pending state swaps label to "Feeding…". */
    .pf-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      height: 38px;
      padding: 0 14px;
      border-radius: 8px;
      border: 1px solid transparent;
      font-size: 13px;
      font-weight: 500;
      line-height: 1;
      cursor: pointer;
      font-family: inherit;
      transition:
        background 0.15s,
        border-color 0.15s,
        opacity 0.15s;
    }
    .pf-btn:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .pf-btn-primary {
      background: var(--petlibro-accent);
      border-color: var(--petlibro-accent);
      color: #fff;
    }
    .pf-btn-primary:hover:not(:disabled) {
      background: color-mix(in srgb, var(--petlibro-accent) 88%, #000);
      border-color: color-mix(in srgb, var(--petlibro-accent) 88%, #000);
    }
    .pf-btn-outline {
      background: transparent;
      border-color: var(--divider-color, #d0d0d0);
      color: var(--primary-text-color);
    }
    .pf-btn-outline:hover:not(:disabled) {
      background: var(--secondary-background-color, #f3f3f3);
    }
    .pf-btn.pending {
      background: color-mix(in srgb, var(--petlibro-accent) 18%, transparent);
      border-color: var(--petlibro-accent);
      color: var(--petlibro-accent);
    }
    .portion-more {
      flex: 0 0 44px !important;
      padding: 0;
      font-size: 18px;
      letter-spacing: 0.05em;
    }
    .portion-cancel {
      flex: 0 0 38px !important;
      padding: 0;
    }
    .portion-cancel ha-icon {
      --mdc-icon-size: 18px;
    }
    .feed-row.custom-portions {
      align-items: stretch;
    }
    .portion-input {
      flex: 1;
      min-width: 0;
      height: 38px;
      font-size: 14px;
      font-weight: 500;
      text-align: center;
      padding: 0 10px;
      border: 1px solid var(--divider-color, #d0d0d0);
      border-radius: 8px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-family: inherit;
      -moz-appearance: textfield;
    }
    /* Native <select> — on iOS this renders as a wheel picker (matching the
       time input in the schedule edit form); desktop browsers show a
       dropdown. Styled to visually match pf-btn for consistency. */
    .portion-select {
      flex: 1;
      min-width: 0;
      height: 38px;
      font-size: 14px;
      font-weight: 500;
      padding: 0 12px;
      border: 1px solid var(--divider-color, #d0d0d0);
      border-radius: 8px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-family: inherit;
      cursor: pointer;
      appearance: menulist;
    }
    .portion-select:focus {
      outline: none;
      border-color: var(--petlibro-accent);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--petlibro-accent) 20%, transparent);
    }
    .portion-input:focus {
      outline: none;
      border-color: var(--petlibro-accent);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--petlibro-accent) 20%, transparent);
    }
    .portion-input::-webkit-outer-spin-button,
    .portion-input::-webkit-inner-spin-button {
      -webkit-appearance: none;
      margin: 0;
    }
    /* ------------------------------ dialog ------------------------------ */
    .dialog-scrim {
      position: fixed;
      inset: 0;
      z-index: 9999;
      background: rgba(0, 0, 0, 0.45);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .dialog {
      width: 100%;
      max-width: 480px;
      max-height: calc(100vh - 48px);
      overflow: auto;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      border-radius: 16px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .dialog-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .dialog-title {
      display: inline-flex;
      align-items: baseline;
      gap: 8px;
      font-size: 18px;
      font-weight: 500;
    }
    .dialog-title ha-icon {
      --mdc-icon-size: 22px;
      color: var(--petlibro-accent);
      position: relative;
      top: 4px;
    }
    .dialog-subtitle {
      font-size: 13px;
      font-weight: 400;
      color: var(--secondary-text-color);
      margin-left: 2px;
    }
    .dialog-close {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color);
      padding: 4px;
    }
    .section {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .section-toolbar {
      display: flex;
      justify-content: flex-end;
    }
    .add-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      border: 1px solid var(--divider-color, #d0d0d0);
      background: var(--card-background-color);
      color: var(--primary-text-color);
      border-radius: 999px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
    }
    .add-btn ha-icon {
      --mdc-icon-size: 14px;
    }
    .empty {
      padding: 12px;
      text-align: center;
      color: var(--secondary-text-color);
      font-size: 13px;
      font-style: italic;
    }
    .log {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .log li {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 8px;
      font-size: 13px;
    }
    .log li.warn {
      background: color-mix(in srgb, var(--petlibro-warn) 18%, transparent);
    }
    .log li ha-icon {
      --mdc-icon-size: 16px;
      color: var(--petlibro-accent);
    }
    .log li.warn ha-icon {
      color: var(--petlibro-warn);
    }
    .log-primary {
      color: var(--primary-text-color);
    }
    .log-time {
      margin-left: auto;
      color: var(--secondary-text-color);
      font-size: 12px;
    }
    .schedules {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .schedules li {
      display: grid;
      grid-template-columns: auto 1fr auto auto auto;
      align-items: center;
      gap: 10px;
      padding: 10px 12px 10px 14px;
      border-radius: 10px;
      border-left: 3px solid transparent;
      transition: background 0.15s, border-color 0.15s, opacity 0.15s;
    }
    .schedules li.enabled {
      background: color-mix(
        in srgb,
        var(--petlibro-accent) 14%,
        var(--card-background-color, #fff)
      );
      border-left-color: var(--petlibro-accent);
    }
    .schedules li.enabled .sched-time {
      color: var(--petlibro-accent);
    }
    .schedules li.disabled {
      background: var(--secondary-background-color, #f5f5f5);
      opacity: 0.6;
      filter: grayscale(0.3);
    }
    .schedules li.disabled .sched-time,
    .schedules li.disabled .sched-portions {
      text-decoration: line-through;
      text-decoration-color: color-mix(
        in srgb, var(--secondary-text-color) 50%, transparent
      );
    }
    .sched-time {
      font-size: 18px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .sched-meta {
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-size: 12px;
      color: var(--secondary-text-color);
    }
    .sched-meta .sched-portions {
      color: var(--primary-text-color);
    }
    .icon-btn {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color);
      padding: 4px;
      border-radius: 6px;
    }
    .icon-btn:hover:not(:disabled) {
      background: rgba(0, 0, 0, 0.06);
      color: var(--primary-text-color);
    }
    .icon-btn:disabled {
      opacity: 0.4;
      cursor: default;
    }
    .icon-btn.danger:hover {
      color: var(--petlibro-error);
    }
    .icon-btn.big ha-icon {
      --mdc-icon-size: 28px;
    }
    /* editor */
    .editor {
      gap: 14px;
    }
    .editor-row {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .editor-row label {
      flex: 0 0 80px;
      font-size: 13px;
      color: var(--secondary-text-color);
    }
    .time-input {
      flex: 1;
      padding: 8px 10px;
      font-size: 16px;
      border: 1px solid var(--divider-color, #d0d0d0);
      border-radius: 8px;
      background: var(--card-background-color);
      color: var(--primary-text-color);
    }
    .stepper {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .stepper-value {
      min-width: 32px;
      text-align: center;
      font-size: 16px;
      font-weight: 500;
    }
    .day-chips {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }
    .day-chip {
      width: 32px;
      height: 32px;
      border-radius: 999px;
      border: 1px solid var(--divider-color, #d0d0d0);
      background: var(--card-background-color);
      color: var(--primary-text-color);
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      position: relative;
    }
    .day-chip sub {
      display: none;
    }
    .day-chip.active {
      background: var(--petlibro-accent);
      color: #fff;
      border-color: var(--petlibro-accent);
    }
    .editor-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      margin-top: 6px;
    }
    .btn {
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      border: 1px solid transparent;
    }
    .btn.ghost {
      background: none;
      color: var(--secondary-text-color);
      border-color: var(--divider-color, #d0d0d0);
    }
    .btn.primary {
      background: var(--petlibro-accent);
      color: #fff;
    }
    .btn:disabled {
      opacity: 0.5;
      cursor: default;
    }
  `,v([G({attribute:!1})],m.prototype,"hass",2),v([x()],m.prototype,"_config",2),v([x()],m.prototype,"_pendingPortions",2),v([x()],m.prototype,"_customPortionsMode",2),v([x()],m.prototype,"_customPortionsValue",2),v([x()],m.prototype,"_dialogMode",2),v([x()],m.prototype,"_editing",2),v([x()],m.prototype,"_editDraft",2),v([x()],m.prototype,"_savingSchedule",2),v([x()],m.prototype,"_optimisticSlots",2),m=v([Et("petlibro-feeder-card")],m);window.customCards=window.customCards??[];window.customCards.push({type:"petlibro-feeder-card",name:"PetLibro Feeder",description:"Status, last-fed, portion feeding, feed log, and schedule editor for a PetLibro feeder.",preview:!1});console.info("%c petlibro-feeder-card %c 0.1.0 ","background:#03a9f4;color:#fff;padding:2px 4px;border-radius:2px 0 0 2px","background:#333;color:#fff;padding:2px 4px;border-radius:0 2px 2px 0");export{m as PetLibroFeederCard};
/*! Bundled license information:

@lit/reactive-element/css-tag.js:
  (**
   * @license
   * Copyright 2019 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/reactive-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/lit-html.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-element/lit-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

lit-html/is-server.js:
  (**
   * @license
   * Copyright 2022 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/custom-element.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/property.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/state.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/event-options.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/base.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-all.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-async.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-assigned-elements.js:
  (**
   * @license
   * Copyright 2021 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)

@lit/reactive-element/decorators/query-assigned-nodes.js:
  (**
   * @license
   * Copyright 2017 Google LLC
   * SPDX-License-Identifier: BSD-3-Clause
   *)
*/
