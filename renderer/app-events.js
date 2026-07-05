document.addEventListener('DOMContentLoaded',function(){
  fgbById('start').onclick=function(){fgbRunning=true;fgbRender()};
  fgbById('pause').onclick=function(){fgbRunning=false;fgbRender()};
  fgbById('reset').onclick=function(){fgbReset()};
  fgbById('render').onclick=function(){alert('Render MP4 will be connected after the Windows build is stable.')};
  fgbById('preset').onchange=function(){fgbApplyPreset(fgbById('preset').value)};
  fgbById('project').onchange=function(){fgbRender()};
  var fields=['episodeNumber','episodeTitle','business','location','contact','promotion'];
  for(var i=0;i<fields.length;i++){fgbById(fields[i]).oninput=function(){fgbRender()}}
  fgbById('minutes').oninput=function(){fgbReset()};
  var buttons=document.querySelectorAll('[data-toggle]');
  for(var b=0;b<buttons.length;b++){buttons[b].onclick=function(){var k=this.getAttribute('data-toggle');fgbVisible[k]=!fgbVisible[k];fgbRender()}}
  fgbReset();fgbApplyPreset('standard');
});
setInterval(function(){if(!fgbRunning){return}if(fgbLeft<=0){fgbRunning=false;fgbRender();return}fgbLeft=fgbLeft-1;fgbRender()},1000);
