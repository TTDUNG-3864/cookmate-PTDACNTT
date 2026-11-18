// MySQL-backed API store. Browser storage is reserved for visual preferences only.
var CookMateStorage = (function () {
  'use strict';

  var API_BASE = String(window.COOKMATE_API_BASE_URL || '').replace(/\/$/, '');
  var state = {
    online: false, user: null, csrfToken: '', recipes: [], myRecipes: [], pendingRecipes: [],
    categories: [], ingredients: [], comments: [], users: [], favorites: [], statistics: {}
  };
  var UI_KEYS = { THEME: 'cookmate_theme' };

  function isHttpMode() {
    return typeof window !== 'undefined' && /^(https?:)$/.test(window.location.protocol);
  }

  function notify(name, detail) {
    try { window.dispatchEvent(new CustomEvent(name, { detail: detail || {} })); } catch (e) {}
  }

  function request(method, path, body) {
    if (!isHttpMode()) return Promise.reject(new Error('CookMate requires the Flask backend for account and data changes.'));
    var tokenPromise = state.csrfToken ? Promise.resolve(state.csrfToken) : fetch(API_BASE + '/api/auth/csrf', { credentials: 'include' })
      .then(function (res) { if (!res.ok) throw new Error('Backend unavailable.'); return res.json(); })
      .then(function (data) { state.csrfToken = data.csrfToken || ''; return state.csrfToken; });
    return tokenPromise.then(function (token) {
      var headers = { 'Content-Type': 'application/json' };
      if (token) headers['X-CSRF-Token'] = token;
      return fetch(API_BASE + path, {
        method: method, headers: headers, credentials: 'include',
        body: body == null || method === 'GET' ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout ? AbortSignal.timeout(10000) : undefined
      });
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (data.csrfToken) state.csrfToken = data.csrfToken;
        if (!response.ok) throw new Error(data.error || 'Không thể hoàn tất thao tác.');
        state.online = true;
        return data;
      });
    }).catch(function (error) {
      if (/Failed to fetch|NetworkError|Backend unavailable|timed out/i.test(error.message || '')) {
        state.online = false;
        notify('cookmate:backend-unavailable', { message: 'Không kết nối được Backend. Các thay đổi chưa được lưu.' });
      }
      throw error;
    });
  }

  function loadAdminData() {
    if (!state.user || state.user.role !== 'admin') return Promise.resolve();
    return Promise.all([
      request('GET', '/api/admin/pending-recipes').then(function (data) { state.pendingRecipes = data.recipes || []; }),
      request('GET', '/api/admin/users').then(function (data) { state.users = data.users || []; })
    ]).catch(function (error) {
      notify('cookmate:backend-unavailable', { message: error.message || 'Không thể tải dữ liệu quản trị.' });
    });
  }

  function initialize() {
    if (!isHttpMode()) return Promise.resolve(false);
    // Establish the signed session cookie and CSRF token before parallel bootstrap
    // reads, so simultaneous first requests cannot overwrite each other's token.
    return fetch(API_BASE + '/api/auth/csrf', { credentials: 'include', signal: AbortSignal.timeout ? AbortSignal.timeout(10000) : undefined })
      .then(function (response) {
        if (!response.ok) throw new Error('Backend unavailable.');
        return response.json();
      })
      .then(function (csrf) {
        state.csrfToken = csrf.csrfToken || '';
        return Promise.all([
          request('GET', '/api/bootstrap'),
          request('GET', '/api/auth/me')
        ]);
      }).then(function (values) {
      var payload = values[0] || {}, auth = values[1] || {};
      state.online = true;
      state.user = auth.user || null;
      state.csrfToken = auth.csrfToken || state.csrfToken;
      state.recipes = payload.recipes || [];
      state.categories = payload.categories || [];
      state.ingredients = payload.ingredients || [];
      state.comments = payload.comments || [];
      state.favorites = payload.favorites || [];
      state.statistics = payload.statistics || {};
      var privateLoad = state.user ? request('GET', '/api/recipes/my').then(function (data) { state.myRecipes = data.recipes || []; }) : Promise.resolve();
      return privateLoad.then(loadAdminData).then(function () {
        notify('cookmate:data-ready', {});
        return true;
      });
    }).catch(function (error) {
      state.online = false;
      state.user = null;
      state.recipes = []; state.myRecipes = []; state.pendingRecipes = []; state.categories = []; state.ingredients = [];
      state.comments = []; state.users = []; state.favorites = [];
      notify('cookmate:backend-unavailable', { message: 'CookMate Backend/MySQL is unavailable. No changes will be saved.' });
      return false;
    });
  }

  var ready = initialize();

  // Existing pages use synchronous DOMContentLoaded setup. Hold those initializers until
  // the first MySQL bootstrap finishes so the data getters read the remote snapshot.
  if (typeof document !== 'undefined') {
    var nativeDocumentAdd = document.addEventListener.bind(document);
    document.addEventListener = function (type, listener, options) {
      if (type === 'DOMContentLoaded' && typeof listener === 'function') {
        var deferred = function (event) { ready.then(function () { listener.call(document, event); }); };
        return nativeDocumentAdd(type, deferred, options);
      }
      return nativeDocumentAdd(type, listener, options);
    };
  }

  function refreshMyRecipes() {
    if (!state.user) return Promise.resolve([]);
    return request('GET', '/api/recipes/my').then(function (data) { state.myRecipes=data.recipes||[]; notify('cookmate:data-ready',{}); return state.myRecipes; });
  }
  function refreshFavorites() {
    if (!state.user) { state.favorites=[]; return Promise.resolve([]); }
    return request('GET','/api/favorites').then(function(data){state.favorites=data.favorites||[];return state.favorites;});
  }

  var store = {
    KEYS: { USER:'cookmate_current_user',ADMIN_SESSION:'cookmate_admin_session',FAVORITES:'cookmate_favorites',USER_RECIPES:'cookmate_user_recipes',DELETED_RECIPES:'cookmate_deleted_recipes',USER_COMMENTS:'cookmate_user_comments',DELETED_COMMENTS:'cookmate_deleted_comments',REGISTERED_USERS:'cookmate_registered_users',USER_STATUS_OVERRIDES:'cookmate_user_status_overrides',ADMIN_CATEGORIES:'cookmate_admin_categories',ADMIN_INGREDIENTS:'cookmate_admin_ingredients',THEME:UI_KEYS.THEME },
    ready: ready,
    isHttpMode: isHttpMode,
    isBackendOnline: function(){return state.online;},
    _apiRequest: request,
    get: function (key) {
      if (!UI_KEYS[key] && key !== UI_KEYS.THEME) return null;
      try { var value=localStorage.getItem(key);return value?JSON.parse(value):null; } catch(e){return null;}
    },
    set: function (key, value) {
      if (key !== UI_KEYS.THEME) return false;
      try { localStorage.setItem(key,JSON.stringify(value));return true; } catch(e){return false;}
    },
    remove: function (key) {
      if (key !== UI_KEYS.THEME) return;
      try { localStorage.removeItem(key); } catch(e) {}
    },
    getCurrentUser: function(){return state.user;},
    setCurrentUser: function(user){state.user=user||null;notify('cookmate:auth-changed',{});return true;},
    clearCurrentUser: function(){state.user=null;state.favorites=[];request('POST','/api/auth/logout',{}).catch(function(){});notify('cookmate:auth-changed',{});},
    getAdminSession: function(){return state.user&&state.user.role==='admin'?state.user:null;},
    setAdminSession: function(){return false;},
    clearAdminSession: function(){},
    isAdminSessionValid: function(){return Boolean(state.user&&state.user.role==='admin');},
    isLoggedIn: function(){return Boolean(state.user);},
    isAdmin: function(){return Boolean(state.user&&state.user.role==='admin');},
    login: function(email,password){return request('POST','/api/auth/login',{email:email,password:password}).then(function(data){state.user=data.user;state.csrfToken=data.csrfToken||state.csrfToken;notify('cookmate:auth-changed',{});return data;});},
    logout: function(){return request('POST','/api/auth/logout',{}).then(function(data){state.user=null;state.favorites=[];notify('cookmate:auth-changed',{});return data;});},
    getFavorites: function(){return state.favorites.slice();},
    toggleFavorite: function(recipeId){
      if(!state.user)return Promise.reject(new Error('Vui lòng đăng nhập để lưu yêu thích.'));
      return request('POST','/api/favorites/toggle',{recipeId:Number(recipeId)}).then(function(result){return refreshFavorites().then(function(){return result;});});
    },
    isFavorite: function(recipeId){return state.favorites.some(function(id){return String(id)===String(recipeId);});},
    getUserRecipes: function(){return state.myRecipes.slice();},
    getDeletedRecipeIds: function(){return [];},
    addUserRecipe: function(recipe){
      if(!state.user)return Promise.reject(new Error('Vui lòng đăng nhập trước khi đăng công thức.'));
      return request('POST','/api/recipes',recipe).then(function(data){
        if(data.recipe){
          state.myRecipes.unshift(data.recipe);
          if(data.recipe.status==='approved') state.recipes.unshift(data.recipe);
        }
        notify('cookmate:data-ready',{});return data.recipe;
      });
    },
    updateUserRecipe: function(id,recipe){
      return request('PUT','/api/recipes/'+encodeURIComponent(id),recipe).then(function(data){
        if(data.recipe){
          state.myRecipes=state.myRecipes.map(function(item){return String(item.id)===String(id)?data.recipe:item;});
          if(data.recipe.status==='approved'){
            var exists=state.recipes.some(function(item){return String(item.id)===String(id);});
            state.recipes=exists?state.recipes.map(function(item){return String(item.id)===String(id)?data.recipe:item;}):[data.recipe].concat(state.recipes);
          }else{
            state.recipes=state.recipes.filter(function(item){return String(item.id)!==String(id);});
          }
        }
        notify('cookmate:data-ready',{});return data.recipe;
      });
    },
    deleteUserRecipe: function(id){
      return request('DELETE','/api/recipes/'+encodeURIComponent(id),{}).then(function(data){
        state.myRecipes=state.myRecipes.filter(function(item){return String(item.id)!==String(id);});
        state.recipes=state.recipes.filter(function(item){return String(item.id)!==String(id);});
        state.pendingRecipes=state.pendingRecipes.filter(function(item){return String(item.id)!==String(id);});
        notify('cookmate:data-ready',{});return data;
      });
    },
    addRecipe: function(recipe){return this.addUserRecipe(recipe);},
    updateRecipe: function(id,updates){return this.updateUserRecipe(id,updates);},
    deleteRecipe: function(id){return this.deleteUserRecipe(id);},
    getPendingRecipes: function(){return state.pendingRecipes.slice();},
    getRejectedRecipes: function(){return state.myRecipes.filter(function(r){return r.status==='rejected';});},
    getApprovedRecipes: function(){return this.getAllRecipes();},
    approveRecipe: function(id){
      return request('POST','/api/admin/recipes/'+encodeURIComponent(id)+'/approve',{}).then(function(data){state.pendingRecipes=state.pendingRecipes.filter(function(r){return String(r.id)!==String(id);});state.recipes.unshift(data.recipe);return data.recipe;});
    },
    rejectRecipe: function(id,reason){
      return request('POST','/api/admin/recipes/'+encodeURIComponent(id)+'/reject',{reason:reason||''}).then(function(data){state.pendingRecipes=state.pendingRecipes.filter(function(r){return String(r.id)!==String(id);});return data.recipe;});
    },
    getRecipeById: function(id,includeUnapproved){
      var all=this.getAllRecipesRaw();var found=all.find(function(r){return String(r.id)===String(id);});
      if(found&&(includeUnapproved||found.status==='approved'||!found.status))return found;
      return null;
    },
    fetchRecipeDetail: function(id,incrementView,includePrivate){
      var qs=[];
      if(incrementView) qs.push('incrementView=1');
      var path=(includePrivate?'/api/admin/recipes/':'/api/recipes/')+encodeURIComponent(id)+(qs.length?'?'+qs.join('&'):'');
      return request('GET',path).then(function(recipe){
        if(recipe&&recipe.id){
          var idx=state.recipes.findIndex(function(r){return String(r.id)===String(recipe.id);});
          if(idx>=0) state.recipes[idx]=recipe;
          else if(recipe.status==='approved') state.recipes.push(recipe);
          state.myRecipes=state.myRecipes.map(function(r){return String(r.id)===String(recipe.id)?recipe:r;});
        }
        return recipe;
      });
    },
    getStatistics: function(){return Object.assign({},state.statistics);},
    submitChatbotFeedback: function(qaId,rating,sessionId){
      return request('POST','/api/chatbot/feedback',{qa_id:Number(qaId),rating:Number(rating),session_id:sessionId||''});
    },
    getCategoryById: function(id){return this.getAllCategories().find(function(c){return String(c.id)===String(id)||c.slug===id;});},
    updateUser: function(updatedUser){return request('PUT','/api/users/profile',updatedUser).then(function(data){state.user=data.user;notify('cookmate:auth-changed',{});return data.user;});},
    setUserStatus: function(userId,status){return request('PUT','/api/admin/users/'+encodeURIComponent(userId)+'/status',{status:status}).then(function(data){state.users=state.users.map(function(u){return String(u.id)===String(userId)?data.user:u;});return data.user;});},
    getUserComments: function(){return state.comments.filter(function(c){return state.user&&String(c.userId)===String(state.user.id);});},
    getDeletedCommentIds: function(){return [];},
    addComment: function(recipeId,content,rating){return request('POST','/api/recipes/'+encodeURIComponent(recipeId)+'/comments',{comment:content,rating:rating||5}).then(function(data){state.comments.unshift(data.comment);return data.comment;});},
    deleteComment: function(commentId){return request('DELETE','/api/comments/'+encodeURIComponent(commentId),{}).then(function(data){state.comments=state.comments.filter(function(c){return String(c.id)!==String(commentId);});return data;});},
    getCommentsForRecipe: function(recipeId){return state.comments.filter(function(c){return String(c.recipeId)===String(recipeId);});},
    getRegisteredUsers: function(){return state.users.slice();},
    getAllUsers: function(){return state.user&&state.user.role==='admin'?state.users.slice():[];},
    registerUser: function(userData){
      return request('POST','/api/auth/register',{name:userData.name,email:userData.email,password:userData.password}).then(function(data){state.user=data.user;state.csrfToken=data.csrfToken||state.csrfToken;notify('cookmate:auth-changed',{});return {user:data.user};});
    },
    getCategories: function(){return state.categories.slice();},
    setCategories: function(cats){return request('PUT','/api/categories/sync',{categories:cats}).then(function(data){state.categories=data.categories||[];notify('cookmate:data-ready',{});return state.categories;});},
    getIngredients: function(){return state.ingredients.slice();},
    setIngredients: function(items){return request('PUT','/api/ingredients/sync',{ingredients:items}).then(function(data){state.ingredients=data.ingredients||[];notify('cookmate:data-ready',{});return state.ingredients;});},
    getAllRecipesRaw: function(){
      if(isHttpMode()&&!state.online)return [];
      var values=state.recipes.concat(state.myRecipes,state.pendingRecipes);var seen={};
      return values.filter(function(r){if(seen[r.id])return false;seen[r.id]=true;return true;});
    },
    getAllRecipes: function(includeAll){var rows=this.getAllRecipesRaw();return includeAll?rows:rows.filter(function(r){return r.status==='approved'||!r.status;});},
    getAllCategories: function(){return isHttpMode()?state.categories.slice():((typeof CATEGORIES!=='undefined')?CATEGORIES.slice():[]);},
    getAllIngredients: function(){return isHttpMode()?state.ingredients.slice():((typeof INGREDIENTS!=='undefined')?INGREDIENTS.slice():[]);},
    getAllComments: function(){return state.comments.slice();},
    resetAll: function(){return Promise.reject(new Error('Reset dữ liệu đã bị tắt để bảo vệ database.'));},
    estimateNutrition: function(ingredients,servings){
      var list=Array.isArray(ingredients)?ingredients:[];
      return request('POST','/api/nutrition/estimate',{ingredients:list,servings:servings||2}).then(function(data){return data.nutrition;});
    }
  };

  // Load MySQL-backed public and session data before existing page initializers run.
  if (isHttpMode()) {
    document.addEventListener('cookmate:backend-unavailable', function(event) {
      var show=function(){
        if(document.getElementById('cookmateBackendNotice'))return;
        var notice=document.createElement('div');notice.id='cookmateBackendNotice';
        notice.setAttribute('role','status');
        notice.textContent=(event.detail&&event.detail.message)||'Backend MySQL tạm thời không khả dụng. Vui lòng kiểm tra kết nối máy chủ.';
        notice.style.cssText='position:fixed;left:12px;bottom:12px;z-index:9997;max-width:min(460px,calc(100vw - 24px));padding:10px 14px;border-radius:10px;background:#fff3cd;color:#664d03;border:1px solid #ffecb5;font:13px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px #0002';
        document.body.appendChild(notice);
      };
      if(document.body)show();else window.addEventListener('load',show,{once:true});
    });
  }

  return store;
})();
