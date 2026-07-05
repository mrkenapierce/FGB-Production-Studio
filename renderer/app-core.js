function fgbById(id){return document.getElementById(id)}
function fgbClock(total){var m=Math.floor(total/60);var s=total%60;return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')}
var fgbTotal=900;
var fgbLeft=900;
var fgbRunning=false;
var fgbPreset='standard';
var fgbProjects={fgb:["Football's Greatest Bears",'FGB'],fgbars:["Football's Greatest Bars",'FGBars'],epic:['EPIC Communities','EPIC']};
var fgbVisible={episodeLine:true,timer:true,status:true,progress:true,partner:false,badge:false,qr:true,brand:true};
function fgbShow(id,on){var node=fgbById(id);if(node){node.classList.toggle('hidden',!on)}}
function fgbApplyPreset(name){fgbPreset=name;var keys=Object.keys(fgbVisible);for(var i=0;i<keys.length;i++){fgbVisible[keys[i]]=false}var list=(window.FGB_PRESETS&&window.FGB_PRESETS[name])||window.FGB_PRESETS.standard;for(var j=0;j<list.length;j++){fgbVisible[list[j]]=true}fgbRender()}
function fgbReset(){fgbTotal=Number(fgbById('minutes').value||15)*60;fgbLeft=fgbTotal;fgbRunning=false;fgbRender()}
function fgbRender(){var p=fgbProjects[fgbById('project').value]||fgbProjects.fgb;fgbById('projectLabel').textContent=p[0];fgbById('brand').textContent=p[1];fgbById('episodeLine').innerHTML='<span class="episode-number">EPISODE '+fgbById('episodeNumber').value+'</span><span class="episode-title">'+fgbById('episodeTitle').value+'</span>';fgbById('timer').textContent=fgbClock(fgbLeft);fgbById('status').textContent=fgbRunning?'Starting Soon':'Ready';fgbById('businessOut').textContent=fgbById('business').value;fgbById('locationOut').textContent=fgbById('location').value;fgbById('contactOut').textContent=fgbById('contact').value;fgbById('promotionOut').textContent=fgbById('promotion').value;var pct=((fgbTotal-fgbLeft)/fgbTotal)*100;fgbById('progress').firstElementChild.style.width=Math.max(0,Math.min(100,pct))+'%';var keys=Object.keys(fgbVisible);for(var i=0;i<keys.length;i++){fgbShow(keys[i],fgbVisible[keys[i]])}}
