import { useEffect, useState } from 'react';
import { api, type Asset, type User } from './api/client';
import { AppShell, type View } from './app/AppShell';
import { AssetDetail } from './pages/AssetDetail';
import { AssetHistory } from './pages/AssetHistory';
import { AssetRegister } from './pages/AssetRegister';
import { LogInspection } from './pages/LogInspection';
import { Login } from './pages/Login';
import { MaintenanceQueue } from './pages/MaintenanceQueue';
import { WorkOrders } from './pages/WorkOrders';

export default function App() {
  const [user, setUser] = useState<User | null>(api.sessionUser);
  const [view, setView] = useState<View>('assets');
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [assetForInspection, setAssetForInspection] = useState<Asset | null>(null);
  const [caseCreation, setCaseCreation] = useState<{ assetId: string; alertId?: string } | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    if (!api.hasToken || api.sessionUser) return;

    api.me()
      .then((restoredUser) => setUser(restoredUser))
      .catch(() => {
        api.clearSession();
        setSessionError('Your session has expired. Please sign in again.');
      });
  }, []);

  function openAsset(asset: Asset): void {
    setSelectedAsset(asset);
    setView('asset-detail');
  }

  function openInspection(asset: Asset): void {
    setAssetForInspection(asset);
    setView('inspection');
  }

  function openHistory(asset: Asset): void {
    setSelectedAsset(asset);
    setView('history');
  }

  function openCases(caseDraft: { assetId: string; alertId?: string } | null = null): void {
    setCaseCreation(caseDraft);
    setView('cases');
  }

  function signOut(): void {
    api.clearSession();
    setUser(null);
    setSelectedAsset(null);
    setAssetForInspection(null);
    setCaseCreation(null);
    setView('assets');
  }

  if (!user) {
    return (
      <Login
        initialError={sessionError}
        onAuthenticated={(authenticatedUser) => {
          setSessionError(null);
          setUser(authenticatedUser);
          setView('assets');
        }}
      />
    );
  }

  return (
    <AppShell onNavigate={setView} onSignOut={signOut} user={user} view={view}>
      {view === 'assets' && (
        <AssetRegister
          onOpenAsset={openAsset}
          onOpenHistory={openHistory}
          onOpenInspection={openInspection}
          user={user}
        />
      )}
      {view === 'asset-detail' && selectedAsset && (
        <AssetDetail
          assetId={selectedAsset.assetId}
          onBack={() => setView('assets')}
          onOpenCases={() => openCases()}
          onOpenHistory={openHistory}
          onOpenInspection={openInspection}
          user={user}
        />
      )}
      {view === 'inspection' && assetForInspection && (
        <LogInspection
          asset={assetForInspection}
          onBack={() => setView('asset-detail')}
          onLogged={(asset) => {
            setSelectedAsset(asset);
            setView('asset-detail');
          }}
        />
      )}
      {view === 'queue' && (
        <MaintenanceQueue
          onCreateCase={(caseDraft) => openCases(caseDraft)}
          onOpenAsset={(assetId) => {
            api.getAsset(assetId).then(openAsset).catch(() => setView('assets'));
          }}
        />
      )}
      {view === 'cases' && (
        <WorkOrders
          initialCreation={caseCreation}
          onCreationOpened={() => setCaseCreation(null)}
          onOpenAsset={(assetId) => {
            api.getAsset(assetId).then(openAsset).catch(() => setView('assets'));
          }}
          user={user}
        />
      )}
      {view === 'history' && selectedAsset && (
        <AssetHistory asset={selectedAsset} onBack={() => setView('asset-detail')} />
      )}
    </AppShell>
  );
}
