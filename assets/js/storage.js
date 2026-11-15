// ===================================================================
// CookMate - LocalStorage & Flask REST API Dual-Mode Management
// ===================================================================

var CookMateStorage = {
  KEYS: {
    USER: 'cookmate_current_user',
    ADMIN_SESSION: 'cookmate_admin_session',
    FAVORITES: 'cookmate_favorites',
    USER_RECIPES: 'cookmate_user_recipes',
    DELETED_RECIPES: 'cookmate_deleted_recipes',
    USER_COMMENTS: 'cookmate_user_comments',
    DELETED_COMMENTS: 'cookmate_deleted_comments',
    REGISTERED_USERS: 'cookmate_registered_users',
    USER_STATUS_OVERRIDES: 'cookmate_user_status_overrides',
    ADMIN_CATEGORIES: 'cookmate_admin_categories',
    ADMIN_INGREDIENTS: 'cookmate_admin_ingredients',
    THEME: 'cookmate_theme'
  },

  // ---------------------------------------------------------------
  // Backend API Helper (Seamless Dual-Mode: Flask SQLite + LocalStorage)
  // ---------------------------------------------------------------
  _isHttpMode: function () {
    return typeof window !== 'undefined' &&
      window.location &&
      (window.location.protocol === 'http:' || window.location.protocol === 'https:');
  },

  _apiRequest: function (method, path, body, callback) {
    if (!this._isHttpMode() || typeof fetch !== 'function') {
      if (callback) callback(null);
      return;
    }
    var headers = { 'Content-Type': 'application/json' };
    var currentUser = this.getCurrentUser();
    if (currentUser && currentUser.id) {
      headers['X-User-Id'] = String(currentUser.id);
    }
    var opts = {
      method: method,
      headers: headers,
      credentials: 'same-origin'
    };
    if (body !== undefined && body !== null && method !== 'GET') {
      opts.body = JSON.stringify(body);
    }
    fetch(path, opts)
      .then(function (res) {
        return res.json().catch(function () { return null; });
      })
      .then(function (data) {
        if (callback) callback(data);
      })
      .catch(function () {
        if (callback) callback(null);
      });
  },

  get: function (key) {
    try {
      var data = localStorage.getItem(key);
      return data ? JSON.parse(data) : null;
    } catch (e) {
      console.warn('CookMateStorage: Error reading', key, e);
      return null;
    }
  },

  set: function (key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      console.warn('CookMateStorage: Error writing', key, e);
      return false;
    }
  },

  remove: function (key) {
    try {
      localStorage.removeItem(key);
    } catch (e) {
      console.warn('CookMateStorage: Error removing', key, e);
    }
  },

  // ---------------------------------------------------------------
  // UC06-B: Automatic Nutrition Estimation from Ingredients
  // ---------------------------------------------------------------
  estimateNutrition: function (ingredientsList, servings) {
    var srv = Math.max(1, parseInt(servings, 10) || 2);
    var masterIngs = this.getAllIngredients();
    var totalCal = 0;
    var totalProt = 0;
    var totalFat = 0;
    var totalCarbs = 0;
    var totalFiber = 0;

    var unitFactors = {
      'g': 0.01,
      'gram': 0.01,
      'gr': 0.01,
      'kg': 10.0,
      'ml': 0.01,
      'lít': 10.0,
      'lit': 10.0,
      'muỗng canh': 0.15,
      'thìa canh': 0.15,
      'muỗng cà phê': 0.05,
      'thìa cà phê': 0.05,
      'quả': 0.6,
      'trái': 0.8,
      'củ': 0.75,
      'bó': 1.5,
      'nhánh': 0.1,
      'tép': 0.05,
      'lá': 0.02,
      'miếng': 0.5,
      'lát': 0.25,
      'cây': 0.4,
      'gói': 1.0,
      'hộp': 1.5,
      'lon': 2.0,
      'chén': 1.5,
      'bát': 2.0,
      'tô': 3.0,
      'con': 1.5
    };

    var list = Array.isArray(ingredientsList) ? ingredientsList : [];
    list.forEach(function (item) {
      if (!item || !item.name) return;
      var rawName = String(item.name).trim().toLowerCase();
      var rawAmt = parseFloat(String(item.amount || '1').replace(',', '.'));
      if (isNaN(rawAmt) || rawAmt <= 0) rawAmt = 1;
      var unit = String(item.unit || '').trim().toLowerCase();
      var factor = (unitFactors[unit] || 0.35) * rawAmt;

      var matched = masterIngs.find(function (m) {
        var mName = String(m.name || '').toLowerCase();
        return mName === rawName || mName.indexOf(rawName) !== -1 || rawName.indexOf(mName) !== -1;
      });

      var calBase = matched ? (parseFloat(matched.calories) || 50) : 85;
      var protBase = matched ? (parseFloat(matched.protein) || 2) : 4;
      var fatBase = matched ? (parseFloat(matched.fat) || 1) : 3;
      var carbBase = matched ? (parseFloat(matched.carbs) || 5) : 10;
      var fibBase = matched ? (parseFloat(matched.fiber) || 0.5) : 1;

      totalCal += calBase * factor;
      totalProt += protBase * factor;
      totalFat += fatBase * factor;
      totalCarbs += carbBase * factor;
      totalFiber += fibBase * factor;
    });

    var perCal = list.length > 0 ? Math.max(120, Math.min(1200, Math.round(totalCal / srv))) : 350;
    var perProt = list.length > 0 ? Math.max(2, Math.round(totalProt / srv)) : 15;
    var perFat = list.length > 0 ? Math.max(2, Math.round(totalFat / srv)) : 10;
    var perCarbs = list.length > 0 ? Math.max(5, Math.round(totalCarbs / srv)) : 40;
    var perFiber = list.length > 0 ? Math.max(1, Math.round(totalFiber / srv)) : 3;

    return {
      calories: perCal,
      protein: perProt,
      fat: perFat,
      carbs: perCarbs,
      fiber: perFiber
    };
  },

  // ---------------------------------------------------------------
  // Current user session & Admin session isolation
  // ---------------------------------------------------------------
  getCurrentUser: function () {
    return this.get(this.KEYS.USER);
  },

  setCurrentUser: function (user) {
    // Never store password
    var safeUser = {};
    Object.keys(user).forEach(function (k) {
      if (k !== 'password' && k !== 'passwordHint' && k !== 'password_hash') {
        safeUser[k] = user[k];
      }
    });

    var result = this.set(this.KEYS.USER, safeUser);

    // Synchronize or isolate Admin Session:
    if (safeUser.role === 'admin') {
      this.setAdminSession(safeUser);
    } else {
      // If a non-admin logs in at top level, invalidate any stale admin session
      if (window.self === window.top) {
        this.clearAdminSession();
      }
    }

    return result;
  },

  clearCurrentUser: function () {
    this.remove(this.KEYS.USER);
    this._apiRequest('POST', '/api/auth/logout', {});
  },

  getAdminSession: function () {
    var session = this.get(this.KEYS.ADMIN_SESSION);
    if (session && session.role === 'admin') {
      return session;
    }
    // Fallback: Check if current active user is admin
    var user = this.getCurrentUser();
    if (user && user.role === 'admin') {
      var adminSess = {
        id: user.id,
        name: user.name,
        email: user.email,
        role: 'admin',
        loginTime: Date.now()
      };
      this.set(this.KEYS.ADMIN_SESSION, adminSess);
      return adminSess;
    }
    return null;
  },

  setAdminSession: function (user) {
    if (user && user.role === 'admin') {
      return this.set(this.KEYS.ADMIN_SESSION, {
        id: user.id,
        name: user.name,
        email: user.email,
        role: 'admin',
        loginTime: Date.now()
      });
    }
    return false;
  },

  clearAdminSession: function () {
    this.remove(this.KEYS.ADMIN_SESSION);
  },

  isAdminSessionValid: function () {
    return this.getAdminSession() !== null;
  },

  isLoggedIn: function () {
    return this.getCurrentUser() !== null;
  },

  isAdmin: function () {
    var user = this.getCurrentUser();
    return user && user.role === 'admin';
  },

  // ---------------------------------------------------------------
  // Favorites (UC13)
  // ---------------------------------------------------------------
  getFavorites: function () {
    return this.get(this.KEYS.FAVORITES) || [];
  },

  toggleFavorite: function (recipeId) {
    var favs = this.getFavorites();
    var numId = Number(recipeId) || recipeId;
    var index = favs.findIndex(function (f) { return f == numId; });
    if (index > -1) {
      favs.splice(index, 1);
    } else {
      favs.push(numId);
    }
    this.set(this.KEYS.FAVORITES, favs);

    var currentUser = this.getCurrentUser();
    this._apiRequest('POST', '/api/favorites/toggle', {
      userId: currentUser ? currentUser.id : 1,
      recipeId: numId
    });

    return index === -1; // true if added, false if removed
  },

  isFavorite: function (recipeId) {
    var favs = this.getFavorites();
    return favs.some(function (f) { return f == recipeId; });
  },

  // ---------------------------------------------------------------
  // User-created recipes & Approval Workflow (UC08-UC10, UC16, UC18)
  // ---------------------------------------------------------------
  getUserRecipes: function () {
    return this.get(this.KEYS.USER_RECIPES) || [];
  },

  getDeletedRecipeIds: function () {
    return this.get(this.KEYS.DELETED_RECIPES) || [];
  },

  addUserRecipe: function (recipe, user) {
    var recipes = this.getUserRecipes();
    var currentUser = user || this.getCurrentUser();

    if (!recipe.id) {
      recipe.id = Date.now();
    }
    recipe.createdAt = recipe.createdAt || new Date().toISOString();
    recipe.isNew = true;

    if (currentUser) {
      recipe.authorId = recipe.authorId || currentUser.id;
      recipe.authorName = recipe.authorName || currentUser.name;
    }

    // Auto-calculate nutrition & calories if not explicitly provided
    if (!recipe.nutrition || !recipe.nutrition.calories) {
      recipe.nutrition = this.estimateNutrition(recipe.ingredients || [], recipe.servings || 2);
    }
    if (!recipe.calories && recipe.nutrition && recipe.nutrition.calories) {
      recipe.calories = recipe.nutrition.calories;
    }

    // Role-based status: Admin directly approves, Member is pending
    if (currentUser && currentUser.role === 'admin') {
      recipe.status = 'approved';
      recipe.approvedAt = new Date().toISOString();
      recipe.approvedBy = currentUser.name;
      recipe.rejectionReason = null;
    } else {
      recipe.status = recipe.status || 'pending';
      recipe.rejectionReason = null;
    }

    recipes.push(recipe);
    this.set(this.KEYS.USER_RECIPES, recipes);

    this._apiRequest('POST', '/api/recipes', Object.assign({}, recipe, {
      actorRole: currentUser ? currentUser.role : 'user'
    }));

    return recipe;
  },

  updateUserRecipe: function (id, updates, user) {
    var recipes = this.getUserRecipes();
    var currentUser = user || this.getCurrentUser();
    var index = recipes.findIndex(function (r) {
      return r.id === id || r.id == id || String(r.id) === String(id);
    });

    // If editing a static recipe (IDs 1-16) not yet in USER_RECIPES, clone it into USER_RECIPES
    if (index === -1 && typeof RECIPES !== 'undefined') {
      var staticFound = RECIPES.find(function (r) {
        return r.id === id || r.id == id || String(r.id) === String(id);
      });
      if (staticFound) {
        var cloned = JSON.parse(JSON.stringify(staticFound));
        cloned.status = cloned.status || 'approved';
        recipes.push(cloned);
        index = recipes.length - 1;
      }
    }

    if (index > -1) {
      var current = recipes[index];

      // If resubmitting a previously rejected recipe
      if (updates.resubmit || (current.status === 'rejected' && (!currentUser || currentUser.role !== 'admin'))) {
        updates.status = 'pending';
        updates.rejectionReason = null;
        updates.resubmittedAt = new Date().toISOString();
      }

      Object.keys(updates).forEach(function (k) {
        if (k !== 'resubmit') {
          recipes[index][k] = updates[k];
        }
      });

      // Re-estimate nutrition when ingredients or servings change
      if ((updates.ingredients || updates.servings) && !updates.nutrition) {
        recipes[index].nutrition = this.estimateNutrition(
          recipes[index].ingredients || [],
          recipes[index].servings || 2
        );
        recipes[index].calories = recipes[index].nutrition.calories;
      }

      recipes[index].updatedAt = new Date().toISOString();
      this.set(this.KEYS.USER_RECIPES, recipes);

      this._apiRequest('PUT', '/api/recipes/' + encodeURIComponent(id), recipes[index]);
      return recipes[index];
    }
    return null;
  },

  deleteUserRecipe: function (id) {
    var recipes = this.getUserRecipes();
    var filtered = recipes.filter(function (r) {
      return r.id !== id && r.id != id && String(r.id) !== String(id);
    });
    var removedFromUser = filtered.length < recipes.length;
    this.set(this.KEYS.USER_RECIPES, filtered);

    // Also record in deleted recipes so static recipes (1-16) can be deleted cleanly
    var deletedIds = this.getDeletedRecipeIds();
    var numId = Number(id) || id;
    var alreadyDeleted = deletedIds.some(function (d) { return d == id; });
    if (!alreadyDeleted) {
      deletedIds.push(numId);
      this.set(this.KEYS.DELETED_RECIPES, deletedIds);
    }

    this._apiRequest('DELETE', '/api/recipes/' + encodeURIComponent(id));
    return removedFromUser || !alreadyDeleted;
  },

  // Aliases for recipe operations
  addRecipe: function (recipe, user) {
    return this.addUserRecipe(recipe, user);
  },

  updateRecipe: function (id, updates, user) {
    return this.updateUserRecipe(id, updates, user);
  },

  deleteRecipe: function (id) {
    return this.deleteUserRecipe(id);
  },

  // Recipe Approval Lifecycle Methods
  getPendingRecipes: function () {
    var deletedIds = this.getDeletedRecipeIds();
    return this.getUserRecipes().filter(function (r) {
      var isDeleted = deletedIds.some(function (d) { return d == r.id; });
      return !isDeleted && r.status === 'pending';
    });
  },

  getRejectedRecipes: function () {
    var deletedIds = this.getDeletedRecipeIds();
    return this.getUserRecipes().filter(function (r) {
      var isDeleted = deletedIds.some(function (d) { return d == r.id; });
      return !isDeleted && r.status === 'rejected';
    });
  },

  getApprovedRecipes: function () {
    return this.getAllRecipes(false);
  },

  approveRecipe: function (id, adminUser) {
    var recipes = this.getUserRecipes();
    var index = recipes.findIndex(function (r) {
      return r.id === id || r.id == id || String(r.id) === String(id);
    });
    if (index > -1) {
      var admin = adminUser || this.getCurrentUser();
      recipes[index].status = 'approved';
      recipes[index].approvedAt = new Date().toISOString();
      recipes[index].approvedBy = admin ? admin.name : 'Quản trị viên';
      recipes[index].rejectionReason = null;
      this.set(this.KEYS.USER_RECIPES, recipes);
      this._apiRequest('POST', '/api/recipes/' + encodeURIComponent(id) + '/approve', {});
      return recipes[index];
    }
    return null;
  },

  rejectRecipe: function (id, reason, adminUser) {
    var recipes = this.getUserRecipes();
    var index = recipes.findIndex(function (r) {
      return r.id === id || r.id == id || String(r.id) === String(id);
    });
    if (index > -1) {
      var admin = adminUser || this.getCurrentUser();
      recipes[index].status = 'rejected';
      recipes[index].rejectedAt = new Date().toISOString();
      recipes[index].rejectedBy = admin ? admin.name : 'Quản trị viên';
      recipes[index].rejectionReason = reason || 'Công thức chưa đáp ứng đầy đủ tiêu chuẩn định lượng của CookMate.';
      this.set(this.KEYS.USER_RECIPES, recipes);
      this._apiRequest('POST', '/api/recipes/' + encodeURIComponent(id) + '/reject', { reason: reason });
      return recipes[index];
    }
    return null;
  },

  getRecipeById: function (id, includeUnapproved) {
    var all = this.getAllRecipesRaw();
    var found = all.find(function (r) {
      return r.id === id || r.id == id || String(r.id) === String(id);
    });
    if (!found) return null;

    if (includeUnapproved || found.status === 'approved' || !found.status) {
      return found;
    }

    var currentUser = this.getCurrentUser();
    if (currentUser && (currentUser.role === 'admin' || currentUser.id === found.authorId)) {
      return found;
    }

    return null;
  },

  getCategoryById: function (id) {
    var numId = parseInt(id, 10);
    return this.getAllCategories().find(function (c) {
      return c.id === numId || c.id == id || c.slug === id;
    });
  },

  updateUser: function (updatedUser) {
    var users = this.getRegisteredUsers();
    var idx = users.findIndex(function (u) { return u.id === updatedUser.id; });
    if (idx !== -1) {
      users[idx] = Object.assign(users[idx], updatedUser);
      this.set(this.KEYS.REGISTERED_USERS, users);
    }
    var current = this.getCurrentUser();
    if (current && current.id === updatedUser.id) {
      this.setCurrentUser(Object.assign(current, updatedUser));
    }
    this._apiRequest('PUT', '/api/users/profile', updatedUser);
    return true;
  },

  setUserStatus: function (userId, status) {
    var overrides = this.get(this.KEYS.USER_STATUS_OVERRIDES) || {};
    overrides[userId] = status;
    this.set(this.KEYS.USER_STATUS_OVERRIDES, overrides);
    this._apiRequest('PUT', '/api/admin/users/' + encodeURIComponent(userId) + '/status', { status: status });
    return true;
  },

  // ---------------------------------------------------------------
  // Comments (UC07, UC21)
  // ---------------------------------------------------------------
  getUserComments: function () {
    return this.get(this.KEYS.USER_COMMENTS) || [];
  },

  getDeletedCommentIds: function () {
    return this.get(this.KEYS.DELETED_COMMENTS) || [];
  },

  addComment: function (recipeId, content, rating) {
    var user = this.getCurrentUser();
    if (!user) return null;
    var comments = this.getUserComments();
    var nowIso = new Date().toISOString();
    var comment = {
      id: Date.now(),
      recipeId: Number(recipeId) || recipeId,
      userId: user.id,
      userName: user.name,
      userAvatar: user.avatar || '',
      rating: rating || 5,
      content: content,
      comment: content,
      date: nowIso.split('T')[0],
      createdAt: nowIso
    };
    comments.push(comment);
    this.set(this.KEYS.USER_COMMENTS, comments);

    this._apiRequest('POST', '/api/recipes/' + encodeURIComponent(recipeId) + '/comments', {
      userId: user.id,
      userName: user.name,
      userAvatar: user.avatar || '',
      rating: rating || 5,
      comment: content
    });

    return comment;
  },

  deleteComment: function (commentId) {
    var comments = this.getUserComments();
    var filtered = comments.filter(function (c) { return c.id != commentId; });
    var removedFromUser = filtered.length < comments.length;
    this.set(this.KEYS.USER_COMMENTS, filtered);

    var deletedIds = this.getDeletedCommentIds();
    var numId = Number(commentId) || commentId;
    if (!deletedIds.some(function (id) { return id == commentId; })) {
      deletedIds.push(numId);
      this.set(this.KEYS.DELETED_COMMENTS, deletedIds);
    }

    this._apiRequest('DELETE', '/api/comments/' + encodeURIComponent(commentId));
    return removedFromUser || true;
  },

  getCommentsForRecipe: function (recipeId) {
    var deletedIds = this.getDeletedCommentIds();
    return this.getUserComments().filter(function (c) {
      var isDeleted = deletedIds.some(function (id) { return id == c.id; });
      return !isDeleted && c.recipeId == recipeId;
    });
  },

  // ---------------------------------------------------------------
  // Registered users (UC11, UC20)
  // ---------------------------------------------------------------
  getRegisteredUsers: function () {
    return this.get(this.KEYS.REGISTERED_USERS) || [];
  },

  registerUser: function (userData, emailArg, passArg) {
    if (typeof userData === 'string') {
      userData = { name: userData, email: emailArg, password: passArg };
    }
    userData = userData || {};
    var users = this.getRegisteredUsers();
    var emailLower = String(userData.email || '').toLowerCase();
    var emailExists = users.some(function (u) {
      return String(u.email || '').toLowerCase() === emailLower;
    });

    // Also check static USERS array if available
    if (!emailExists && typeof USERS !== 'undefined') {
      emailExists = USERS.some(function (u) {
        return String(u.email || '').toLowerCase() === emailLower;
      });
    }

    if (emailExists) return { error: 'Email đã được sử dụng' };

    var newUser = {
      id: Date.now(),
      name: userData.name,
      email: userData.email,
      role: 'member',
      avatar: '',
      joinDate: new Date().toISOString().split('T')[0],
      bio: '',
      recipeCount: 0,
      status: 'active'
    };
    users.push(newUser);
    this.set(this.KEYS.REGISTERED_USERS, users);

    // Store password hint separately (demo only, NOT secure)
    var creds = this.get('cookmate_demo_creds') || [];
    creds.push({
      email: userData.email,
      passwordHint: userData.password,
      userId: newUser.id
    });
    this.set('cookmate_demo_creds', creds);

    this._apiRequest('POST', '/api/auth/register', {
      name: userData.name,
      email: userData.email,
      password: userData.password
    });

    return { user: newUser };
  },

  // ---------------------------------------------------------------
  // Admin categories / ingredients overrides (UC17, UC19)
  // ---------------------------------------------------------------
  getCategories: function () {
    return this.get(this.KEYS.ADMIN_CATEGORIES);
  },

  setCategories: function (cats) {
    this.set(this.KEYS.ADMIN_CATEGORIES, cats);
    this._apiRequest('PUT', '/api/categories/sync', { categories: cats });
  },

  getIngredients: function () {
    return this.get(this.KEYS.ADMIN_INGREDIENTS);
  },

  setIngredients: function (ings) {
    this.set(this.KEYS.ADMIN_INGREDIENTS, ings);
    this._apiRequest('PUT', '/api/ingredients/sync', { ingredients: ings });
  },

  // ---------------------------------------------------------------
  // Get all data combined (static + user-created + overrides)
  // ---------------------------------------------------------------
  getAllRecipesRaw: function () {
    var deletedIds = this.getDeletedRecipeIds();
    var userRecipes = this.getUserRecipes().filter(function (r) {
      return !deletedIds.some(function (d) { return d == r.id; });
    });
    var userIds = userRecipes.map(function (r) { return String(r.id); });

    var staticRecipes = (typeof RECIPES !== 'undefined') ? RECIPES.filter(function (r) {
      var isDeleted = deletedIds.some(function (d) { return d == r.id; });
      var isOverridden = userIds.indexOf(String(r.id)) !== -1;
      return !isDeleted && !isOverridden;
    }) : [];

    return staticRecipes.concat(userRecipes);
  },

  getAllRecipes: function (includeAll) {
    var raw = this.getAllRecipesRaw();
    if (includeAll === true) {
      return raw;
    }
    // Public recipes only: status is 'approved' or untagged static recipe
    return raw.filter(function (r) {
      return r.status === 'approved' || !r.status;
    });
  },

  getAllUsers: function () {
    var staticUsers = (typeof USERS !== 'undefined') ? USERS.slice() : [];
    var registered = this.getRegisteredUsers();
    var overrides = this.get(this.KEYS.USER_STATUS_OVERRIDES) || {};
    return staticUsers.concat(registered).map(function (u) {
      var copy = Object.assign({}, u);
      if (overrides[copy.id]) {
        copy.status = overrides[copy.id];
      } else {
        copy.status = copy.status || 'active';
      }
      return copy;
    });
  },

  getAllCategories: function () {
    var saved = this.getCategories();
    if (saved) return saved;
    return (typeof CATEGORIES !== 'undefined') ? CATEGORIES.slice() : [];
  },

  getAllIngredients: function () {
    var saved = this.getIngredients();
    if (saved) return saved;
    return (typeof INGREDIENTS !== 'undefined') ? INGREDIENTS.slice() : [];
  },

  getAllComments: function () {
    var deletedIds = this.getDeletedCommentIds();
    var staticComments = [];
    if (typeof RECIPES !== 'undefined') {
      RECIPES.forEach(function (r) {
        if (r.comments) {
          r.comments.forEach(function (c) {
            var copy = {};
            Object.keys(c).forEach(function (k) { copy[k] = c[k]; });
            copy.recipeId = r.id;
            copy.content = copy.content || copy.comment || '';
            copy.createdAt = copy.createdAt || copy.date || '';
            staticComments.push(copy);
          });
        }
      });
    }
    var userComments = this.getUserComments();
    return staticComments.concat(userComments).filter(function (c) {
      return !deletedIds.some(function (id) { return id == c.id; });
    });
  },

  // ---------------------------------------------------------------
  // Reset all demo data
  // ---------------------------------------------------------------
  resetAll: function () {
    var self = this;
    Object.values(this.KEYS).forEach(function (key) {
      self.remove(key);
    });
    this.remove('cookmate_demo_creds');
    this._apiRequest('POST', '/api/admin/reset', {});
  }
};
