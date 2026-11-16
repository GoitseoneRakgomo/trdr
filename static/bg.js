/* Flowing lime ribbon background, same motion language as the Relay page */
(function(){
  var c=document.getElementById('bg');if(!c)return;
  var x=c.getContext('2d'),W,H,N=60,P=60,sp=[],bx=[],by=[],nx=[],ny=[],wd=[],last=0,dt=0,
  mo=matchMedia('(prefers-reduced-motion: reduce)').matches,cp=0;
  function fit(){var D=Math.min(devicePixelRatio||1,1.5),m=innerWidth<700;W=innerWidth;H=innerHeight;
    c.width=W*D;c.height=H*D;x.setTransform(D,0,0,D,0,0);N=m?30:60;P=m?40:60;sp=[];
    for(var i=0;i<(m?24:70);i++)sp.push({u:Math.random(),t:Math.random(),v:.02+Math.random()*.05,r:.5+Math.random()*1.3});
    if(mo)draw(4)}
  function base(T){var hs=H*.22,pu=.22+.5*cp,j;
    for(j=0;j<=P;j++){var u=j/P;bx[j]=(-.1+1.2*u)*W;
      by[j]=.5*H+.15*H*Math.sin(u*4.2+T*.15)+.06*H*Math.sin(u*9-T*.5);
      wd[j]=hs*(.07+Math.min(1.25,Math.pow(Math.abs(u-pu)*1.7,1.2)))}
    for(j=0;j<=P;j++){var a=by[Math.min(P,j+1)]-by[Math.max(0,j-1)],b=bx[Math.min(P,j+1)]-bx[Math.max(0,j-1)],l=Math.hypot(a,b)||1;nx[j]=-a/l;ny[j]=b/l}}
  function ln(o,ph){x.beginPath();for(var j=0;j<=P;j++){var d=o*wd[j]*(1+.2*Math.sin(ph+j/P*4)),px=bx[j]+nx[j]*d,py=by[j]+ny[j]*d;j?x.lineTo(px,py):x.moveTo(px,py)}}
  function draw(T){var g=.14,i,j;
    x.globalCompositeOperation='source-over';x.clearRect(0,0,W,H);x.globalCompositeOperation='lighter';base(T);
    var jp=Math.round(P*(.22+.5*cp)),gr=x.createRadialGradient(bx[jp],by[jp],0,bx[jp],by[jp],H*.5);
    gr.addColorStop(0,'rgba(198,244,0,'+(g+.05)+')');gr.addColorStop(1,'rgba(198,244,0,0)');x.fillStyle=gr;x.fillRect(0,0,W,H);
    x.lineJoin='round';x.lineCap='round';
    for(i=0;i<N;i++){var t=i/(N-1),e=Math.abs(t-.5)*2;
      x.strokeStyle='hsla('+(70+e*e*100)+',95%,'+(52+8*(1-e))+'%,'+(.08+.3*(1-e))+')';
      x.lineWidth=.6+(i%5)*.25;ln(t-.5,T*.7+t*6);x.stroke()}
    for(i=0;i<sp.length;i++){var s=sp[i];s.u=(s.u+s.v*dt)%1;j=Math.round(s.u*P);
      var o=(s.t-.5)*wd[j];
      x.fillStyle='rgba(225,255,100,'+(.6*(.5+.5*Math.sin(T*3+s.t*20)))+')';x.beginPath();x.arc(bx[j]+nx[j]*o,by[j]+ny[j]*o,s.r,0,6.3);x.fill()}
    var m=x.createLinearGradient(0,0,W,0);x.globalCompositeOperation='destination-in';
    m.addColorStop(0,'rgba(0,0,0,0)');m.addColorStop(.08,'#000');m.addColorStop(.92,'#000');m.addColorStop(1,'rgba(0,0,0,0)');
    x.fillStyle=m;x.fillRect(0,0,W,H)}
  function loop(ms){var T=ms/1000;dt=Math.min(T-last,.05);last=T;
    var d=document.documentElement,t=Math.max(0,Math.min(1,scrollY/Math.max(1,d.scrollHeight-H)));cp+=(t-cp)*(1-Math.exp(-dt*5));
    draw(T);requestAnimationFrame(loop)}
  addEventListener('resize',fit);fit();if(!mo)requestAnimationFrame(loop);
  var els=[].slice.call(document.querySelectorAll('h1,h2,.lead,.eyebrow,.card,.tag'));
  els.forEach(function(e,i){e.style.setProperty('--d',Math.min(i%6,5)*.07+'s');e.classList.add('rv')});
  if('IntersectionObserver' in window){var io=new IntersectionObserver(function(en){en.forEach(function(r){if(r.isIntersecting)r.target.classList.add('in')})},{threshold:.08});
    els.forEach(function(e){io.observe(e)})}else els.forEach(function(e){e.classList.add('in')});
})();
