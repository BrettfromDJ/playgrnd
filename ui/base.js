/* Just enough behaviour to feel the controls: sliders update their readout
   and fill, toggles toggle, chips and tiles select, tabs switch panes. */
(function(){
  function fill(r){ var p=(r.value-r.min)/(r.max-r.min)*100; r.style.setProperty("--p",p+"%"); }
  document.querySelectorAll(".dial input[type=range]").forEach(function(r){
    var out=r.closest(".dial").querySelector(".val,.val-in");
    var fmt=r.dataset.fmt||"pct";
    function show(){ if(!out)return; var v=+r.value; var t=fmt==="int"?String(v):fmt==="px"?v+" px":fmt==="fps"?v+" fps":fmt==="fr"?v+" frames":Math.round(v*100)+"%";
      if(out.tagName==="INPUT") out.value=t; else out.textContent=t; }
    r.addEventListener("input",function(){ fill(r); show(); });
    fill(r); show();
  });
  document.querySelectorAll("[aria-pressed]").forEach(function(b){
    b.addEventListener("click",function(){
      var grp=b.closest("[data-one]");
      if(grp){ grp.querySelectorAll("[aria-pressed]").forEach(function(x){ x.setAttribute("aria-pressed","false"); }); b.setAttribute("aria-pressed","true"); }
      else b.setAttribute("aria-pressed", b.getAttribute("aria-pressed")==="true"?"false":"true");
      var body=b.dataset.body&&document.getElementById(b.dataset.body); if(body) body.hidden=b.getAttribute("aria-pressed")!=="true";
    });
  });
  document.querySelectorAll("[data-tabs]").forEach(function(t){
    var tabs=t.querySelectorAll("[data-tab]");
    tabs.forEach(function(b){ b.addEventListener("click",function(){
      tabs.forEach(function(x){ x.setAttribute("aria-selected","false"); document.getElementById(x.dataset.tab).hidden=true; });
      b.setAttribute("aria-selected","true"); document.getElementById(b.dataset.tab).hidden=false;
    }); });
  });
  document.querySelectorAll("[data-open]").forEach(function(b){ b.addEventListener("click",function(){
    var el=document.getElementById(b.dataset.open); if(!el)return;
    var on=el.classList.toggle("open"); document.body.classList.toggle("sheet-open",on);
  }); });
  document.querySelectorAll("[data-close]").forEach(function(b){ b.addEventListener("click",function(){
    var el=document.getElementById(b.dataset.close); if(el){ el.classList.remove("open"); document.body.classList.remove("sheet-open"); }
  }); });
  var arts=["../art/crowd.jpg","../art/vein.jpg","../art/motley.jpg"], ai=0;
  document.querySelectorAll("[data-new]").forEach(function(b){ b.addEventListener("click",function(){
    ai=(ai+1)%arts.length; document.querySelectorAll(".art").forEach(function(im){ im.src=arts[ai]; });
    var s=document.querySelector(".seedbox input"); if(s) s.value=Math.floor(Math.random()*99999)+1;
  }); });
})();
