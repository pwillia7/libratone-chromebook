.class public final Lcom/libratone/v3/luci/ArcBtCompat;
.super Landroid/content/BroadcastReceiver;
.implements Ljava/lang/Runnable;

# ChromeOS/ARC compatibility helper (patch #2, revised 2026-10-01).
#
# ARC mirrors ChromeOS's physical (ACL) link state into BluetoothDevice.isConnected()
# and sends ACTION_ACL_CONNECTED / ACTION_ACL_DISCONNECTED, but does not send the
# A2DP CONNECTION_STATE_CHANGED broadcast Libratone relies on. This class lets
# BlueToothUtil track only the Libratone speakers that are actually connected,
# instead of treating every bonded speaker as connected.
#
# All entry points run on the main thread (registerBTClassicReceiver callers and
# the main-looper Handler below), so no locking is needed.


# static fields
.field private static sHandler:Landroid/os/Handler;

.field private static sInstance:Lcom/libratone/v3/luci/ArcBtCompat;


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Landroid/content/BroadcastReceiver;-><init>()V

    return-void
.end method

.method public static isConnected(Landroid/bluetooth/BluetoothDevice;)Z
    .locals 4

    const/4 v0, 0x0

    if-nez p0, :cond_0

    return v0

    :cond_0
    :try_start_0
    const-class v1, Landroid/bluetooth/BluetoothDevice;

    const-string v2, "isConnected"

    new-array v3, v0, [Ljava/lang/Class;

    invoke-virtual {v1, v2, v3}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;

    move-result-object v1

    const/4 v2, 0x1

    invoke-virtual {v1, v2}, Ljava/lang/reflect/Method;->setAccessible(Z)V

    new-array v2, v0, [Ljava/lang/Object;

    invoke-virtual {v1, p0, v2}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;

    move-result-object v1

    instance-of v2, v1, Ljava/lang/Boolean;

    if-eqz v2, :cond_1

    check-cast v1, Ljava/lang/Boolean;

    invoke-virtual {v1}, Ljava/lang/Boolean;->booleanValue()Z

    move-result v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :cond_1
    return v0

    :catch_0
    const/4 v0, 0x0

    return v0
.end method

.method public static ensureAclReceiver()V
    .locals 5

    sget-object v0, Lcom/libratone/v3/luci/ArcBtCompat;->sInstance:Lcom/libratone/v3/luci/ArcBtCompat;

    if-eqz v0, :cond_0

    return-void

    :cond_0
    :try_start_0
    invoke-static {}, Lcom/libratone/v3/LibratoneApplication;->getContext()Landroid/content/Context;

    move-result-object v0

    if-nez v0, :cond_1

    return-void

    :cond_1
    invoke-virtual {v0}, Landroid/content/Context;->getApplicationContext()Landroid/content/Context;

    move-result-object v0

    new-instance v1, Lcom/libratone/v3/luci/ArcBtCompat;

    invoke-direct {v1}, Lcom/libratone/v3/luci/ArcBtCompat;-><init>()V

    new-instance v2, Landroid/content/IntentFilter;

    invoke-direct {v2}, Landroid/content/IntentFilter;-><init>()V

    const-string v3, "android.bluetooth.device.action.ACL_CONNECTED"

    invoke-virtual {v2, v3}, Landroid/content/IntentFilter;->addAction(Ljava/lang/String;)V

    const-string v3, "android.bluetooth.device.action.ACL_DISCONNECTED"

    invoke-virtual {v2, v3}, Landroid/content/IntentFilter;->addAction(Ljava/lang/String;)V

    sget v3, Landroid/os/Build$VERSION;->SDK_INT:I

    const/16 v4, 0x21

    if-lt v3, v4, :cond_2

    # Context.RECEIVER_EXPORTED (system broadcasts), matching the app's own BT receiver.
    const/4 v3, 0x2

    invoke-virtual {v0, v1, v2, v3}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;I)Landroid/content/Intent;

    goto :goto_0

    :cond_2
    invoke-virtual {v0, v1, v2}, Landroid/content/Context;->registerReceiver(Landroid/content/BroadcastReceiver;Landroid/content/IntentFilter;)Landroid/content/Intent;

    :goto_0
    sput-object v1, Lcom/libratone/v3/luci/ArcBtCompat;->sInstance:Lcom/libratone/v3/luci/ArcBtCompat;

    const-string v0, "ArcBtCompat"

    const-string v1, "ACL receiver registered"

    invoke-static {v0, v1}, Lcom/libratone/v3/util/GTLog;->d(Ljava/lang/String;Ljava/lang/String;)V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    return-void

    :catch_0
    move-exception v0

    const-string v1, "ArcBtCompat"

    invoke-virtual {v0}, Ljava/lang/Throwable;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-static {v1, v0}, Lcom/libratone/v3/util/GTLog;->e(Ljava/lang/String;Ljava/lang/String;)V

    return-void
.end method


# virtual methods
.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 3

    # Re-sync (debounced) shortly after a link change so isConnected() reflects the new state.
    sget-object v0, Lcom/libratone/v3/luci/ArcBtCompat;->sHandler:Landroid/os/Handler;

    if-nez v0, :cond_0

    new-instance v0, Landroid/os/Handler;

    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;

    move-result-object v1

    invoke-direct {v0, v1}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V

    sput-object v0, Lcom/libratone/v3/luci/ArcBtCompat;->sHandler:Landroid/os/Handler;

    :cond_0
    invoke-virtual {v0, p0}, Landroid/os/Handler;->removeCallbacks(Ljava/lang/Runnable;)V

    const-wide/16 v1, 0x3e8

    invoke-virtual {v0, p0, v1, v2}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z

    return-void
.end method

.method public run()V
    .locals 1

    :try_start_0
    invoke-static {}, Lcom/libratone/v3/luci/BlueToothUtil;->getInstance()Lcom/libratone/v3/luci/BlueToothUtil;

    move-result-object v0

    invoke-virtual {v0}, Lcom/libratone/v3/luci/BlueToothUtil;->arcSyncConnectedProducts()V
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    :catch_0
    return-void
.end method
