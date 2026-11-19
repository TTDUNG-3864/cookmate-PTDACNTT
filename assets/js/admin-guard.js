// Admin pages are hidden until the server confirms the session role.
(function () {
  'use strict';
  var base=String(window.COOKMATE_API_BASE_URL||'').replace(/\/$/,'');
  var target=window.location.pathname.split('/').slice(-1)[0]||'index.html';
  var adminUser=null;
  var root=document.documentElement;
  if(root)root.style.visibility='hidden';

  function deny(user) {
    if(user)window.location.replace('../../index.html');
    else {
      var path=window.location.pathname;var idx=path.indexOf('pages/admin/');
      var relative=idx>=0?path.substring(idx):'pages/admin/'+target;
      window.location.replace('../auth/login.html?redirect='+encodeURIComponent(relative));
    }
  }

  window.__COOKMATE_ADMIN_AUTH_READY__=fetch(base+'/api/auth/me',{credentials:'include',headers:{'Accept':'application/json'}})
    .then(function(response){if(!response.ok)throw new Error('Backend unavailable');return response.json();})
    .then(function(data){
      window.__COOKMATE_CSRF_TOKEN__=data&&data.csrfToken||'';
      var usr=data&&data.authenticated&&data.user?data.user:null;
      if(usr&&(usr.must_change_password||usr.mustChangePassword)){
        if(root)root.style.visibility='';
        return false;
      }
      adminUser=usr&&usr.role==='admin'?usr:null;
      window.__COOKMATE_ADMIN_USER__=adminUser;
      if(adminUser){if(root)root.style.visibility='';return true;}
      deny(usr);return false;
    })
    .catch(function(){
      if(root)root.style.visibility='';
      window.addEventListener('DOMContentLoaded',function(){
        if(document.body){var notice=document.createElement('div');notice.setAttribute('role','alert');notice.textContent='Không thể xác thực Admin với Backend. Hãy kiểm tra kết nối rồi tải lại trang.';notice.style.cssText='margin:24px;padding:16px;background:#fff3cd;color:#664d03;border-radius:10px;font:14px system-ui';document.body.prepend(notice);}
      },{once:true});
      return false;
    });

  // Keep existing synchronous page initializers behind server-side role verification.
  var nativeAdd=document.addEventListener.bind(document);
  document.addEventListener=function(type,listener,options){
    if(type==='DOMContentLoaded'&&typeof listener==='function'){
      return nativeAdd(type,function(event){window.__COOKMATE_ADMIN_AUTH_READY__.then(function(){if(adminUser)listener.call(document,event);});},options);
    }
    return nativeAdd(type,listener,options);
  };

  window.checkAdminAuth=function(){
    if(!adminUser)return false;
    var name=document.getElementById('adminUserName');var avatar=document.getElementById('adminUserAvatar');
    if(name)name.textContent=adminUser.name;
    if(avatar)avatar.textContent=String(adminUser.name||'A').charAt(0).toUpperCase();
    return true;
  };

  window.handleAdminLogout=function(){
    var token=window.__COOKMATE_CSRF_TOKEN__||'';
    fetch(base+'/api/auth/logout',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:'{}'})
      .catch(function(){})
      .finally(function(){window.location.replace('../../index.html');});
  };
  window.handleLogout=window.handleAdminLogout;
  window.addEventListener('pageshow',function(event){if(event.persisted)window.location.reload();});
})();
