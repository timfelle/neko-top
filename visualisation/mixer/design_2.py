# state file generated using paraview version 6.1.1
import paraview
paraview.compatibility.major = 6
paraview.compatibility.minor = 1

#### import the simple module from the paraview
from paraview.simple import *
#### disable automatic camera reset on 'Show'
paraview.simple._DisableFirstRenderCameraReset()

# ----------------------------------------------------------------
# setup views used in the visualization
# ----------------------------------------------------------------

# Create a new 'Render View'
renderView1 = CreateView('RenderView')
renderView1.Set(
    ViewSize=[3251, 1325],
    AxesGrid='Grid Axes 3D Actor',
    OrientationAxesVisibility=0,
    CenterOfRotation=[2.0, 0.5, 0.5],
    CameraPosition=[-0.4511849438187457, 0.8931223957748938, 2.91550839947204],
    CameraFocalPoint=[4.311629725477945, -0.7054890391110707, -3.5603662474322078],
    CameraViewUp=[0.11333016892331155, 0.980790710365838, -0.15876351996566657],
)

SetActiveView(None)

# ----------------------------------------------------------------
# setup view layouts
# ----------------------------------------------------------------

# create new layout object 'Layout #1'
layout1 = CreateLayout(name='Layout #1')
layout1.AssignView(0, renderView1)
layout1.SetSize(3251, 1325)

# ----------------------------------------------------------------
# restore active view
SetActiveView(renderView1)
# ----------------------------------------------------------------

# ----------------------------------------------------------------
# setup the data processing pipelines
# ----------------------------------------------------------------

# create a new 'VTKHDF Reader'
design_0vtkhdf = VTKHDFReader(registrationName='design_0.vtkhdf', FileName=['C:/Users/tife/Downloads/steady_200_short_small/design_0.vtkhdf'])
design_0vtkhdf.PointArrayStatus = ['PDE_filter_mapping', 'brinkman_amplitude', 'design_indicator']

# create a new 'Merge Blocks'
mergeBlocks1 = MergeBlocks(registrationName='MergeBlocks1', Input=design_0vtkhdf)

# create a new 'VTKHDF Reader'
forward_fields_0vtkhdf = VTKHDFReader(registrationName='forward_fields_0.vtkhdf', FileName=['C:/Users/tife/Downloads/steady_200_short_small/forward_fields_0.vtkhdf'])
forward_fields_0vtkhdf.PointArrayStatus = ['Pressure', 'Velocity', 's']

# create a new 'Merge Blocks'
mergeBlocks2 = MergeBlocks(registrationName='MergeBlocks2', Input=forward_fields_0vtkhdf)

# create a new 'Slice'
slice1 = Slice(registrationName='Slice1', Input=mergeBlocks2)
slice1.Set(
    SliceType='Plane',
    Crinkleslice=1,
    PointMergeMethod='Not Merging Points',
)

# init the 'Plane' selected for 'SliceType'
slice1.SliceType.Origin = [0.001, 0.5, 0.5]

# init the 'Plane' selected for 'HyperTreeGridSlicer'
slice1.HyperTreeGridSlicer.Origin = [2.0, 0.5, 0.5]

# create a new 'Slice'
slice2 = Slice(registrationName='Slice2', Input=mergeBlocks2)
slice2.Set(
    SliceType='Plane',
    Crinkleslice=1,
    PointMergeMethod='Not Merging Points',
)

# init the 'Plane' selected for 'SliceType'
slice2.SliceType.Origin = [3.999999, 0.5, 0.5]

# init the 'Plane' selected for 'HyperTreeGridSlicer'
slice2.HyperTreeGridSlicer.Origin = [2.0, 0.5, 0.5]

# create a new 'VTKm Clip'
vTKmClip1 = VTKmClip(registrationName='VTKmClip1', Input=mergeBlocks1)
vTKmClip1.Set(
    Scalars=['POINTS', 'PDE_filter_mapping'],
    ClipValue=0.001,
)

# create a new 'VTKm Contour'
vTKmContour1 = VTKmContour(registrationName='VTKmContour1', Input=vTKmClip1)
vTKmContour1.Set(
    ContourBy=['POINTS', 'PDE_filter_mapping'],
    Isosurfaces=[0.9],
)

# create a new 'Smooth'
smooth1 = Smooth(registrationName='Smooth1', Input=vTKmContour1)
smooth1.Convergence = 0.0001

# create a new 'Clip Closed Surface'
clipClosedSurface1 = ClipClosedSurface(registrationName='ClipClosedSurface1', Input=smooth1)
clipClosedSurface1.ClippingPlane = 'Plane'

# init the 'Plane' selected for 'ClippingPlane'
clipClosedSurface1.ClippingPlane.Normal = [0.0, 1.0, 0.0]

# create a new 'Clip Closed Surface'
clipClosedSurface2 = ClipClosedSurface(registrationName='ClipClosedSurface2', Input=clipClosedSurface1)
clipClosedSurface2.ClippingPlane = 'Plane'

# init the 'Plane' selected for 'ClippingPlane'
clipClosedSurface2.ClippingPlane.Set(
    Origin=[0.0, 0.0, 1.0],
    Normal=[0.0, 0.0, -1.0],
)

# ----------------------------------------------------------------
# setup the visualization in view 'renderView1'
# ----------------------------------------------------------------

# show data from vTKmClip1
vTKmClip1Display = Show(vTKmClip1, renderView1, 'UnstructuredGridRepresentation')

# get color transfer function/color map for 'PDE_filter_mapping'
pDE_filter_mappingLUT = GetColorTransferFunction('PDE_filter_mapping')
pDE_filter_mappingLUT.Set(
    AutomaticRescaleRangeMode='Never',
    RGBPoints=GenerateRGBPoints(
        preset_name='Grayscale',
    ),
    ColorSpace='RGB',
    NanColor=[1.0, 0.0, 0.0],
    Discretize=0,
    ScalarRangeInitialized=1.0,
)

# get opacity transfer function/opacity map for 'PDE_filter_mapping'
pDE_filter_mappingPWF = GetOpacityTransferFunction('PDE_filter_mapping')
pDE_filter_mappingPWF.Set(
    Points=[0.0, 0.0, 0.5, 0.0, 0.01, 0.1, 0.5, 0.0, 0.9, 0.2, 0.5, 0.0, 0.9, 1.0, 0.5, 0.0, 1.0, 0.0, 0.5, 0.0],
    ScalarRangeInitialized=1,
)

# trace defaults for the display properties.
vTKmClip1Display.Set(
    Representation='Volume',
    ColorArrayName=['POINTS', 'PDE_filter_mapping'],
    LookupTable=pDE_filter_mappingLUT,
    UseDataPartitions=1,
    Assembly='Hierarchy',
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
    ScalarOpacityFunction=pDE_filter_mappingPWF,
    ScalarOpacityUnitDistance=0.02,
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
vTKmClip1Display.ScaleTransferFunction.Points = [-0.005905456375330687, 0.0, 0.5, 0.0, 1.0175633430480957, 1.0, 0.5, 0.0]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
vTKmClip1Display.OpacityTransferFunction.Points = [-0.005905456375330687, 0.0, 0.5, 0.0, 1.0175633430480957, 1.0, 0.5, 0.0]

# show data from mergeBlocks1
mergeBlocks1Display = Show(mergeBlocks1, renderView1, 'UnstructuredGridRepresentation')

# trace defaults for the display properties.
mergeBlocks1Display.Set(
    Representation='Outline',
    ColorArrayName=[None, ''],
    LineWidth=2.0,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
mergeBlocks1Display.ScaleTransferFunction.Points = [-0.0007598351803608239, 0.0, 0.5, 0.0, 1.0186811685562134, 1.0, 0.5, 0.0]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
mergeBlocks1Display.OpacityTransferFunction.Points = [-0.0007598351803608239, 0.0, 0.5, 0.0, 1.0186811685562134, 1.0, 0.5, 0.0]

# show data from slice1
slice1Display = Show(slice1, renderView1, 'UnstructuredGridRepresentation')

# get color transfer function/color map for 's'
sLUT = GetColorTransferFunction('s')
sLUT.Set(
    AutomaticRescaleRangeMode='Never',
    RGBPoints=[
        # scalar, red, green, blue
        0.0, 0.0, 0.0, 0.2,
        0.25, 0.0, 0.0, 0.5,
        0.475, 0.0, 0.8, 0.8,
        0.5, 1.0, 1.0, 1.0,
        0.525, 0.8, 0.8, 0.0,
        0.75, 0.5, 0.0, 0.0,
        1.0, 0.2, 0.0, 0.0,
    ],
    ColorSpace='RGB',
    Discretize=0,
    ScalarRangeInitialized=1.0,
)

# trace defaults for the display properties.
slice1Display.Set(
    Representation='Surface With Edges',
    ColorArrayName=['POINTS', 's'],
    LookupTable=sLUT,
    LineWidth=3.0,
    RenderLinesAsTubes=1,
    DisableLighting=1,
    EdgeColor=[1.0, 1.0, 1.0],
    EdgeOpacity=0.5,
    NonlinearSubdivisionLevel=2,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
slice1Display.ScaleTransferFunction.Points = [0.0, 0.0, 0.5, 0.0, 1.1757813367477812e-38, 1.0, 0.5, 0.0]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
slice1Display.OpacityTransferFunction.Points = [0.0, 0.0, 0.5, 0.0, 1.1757813367477812e-38, 1.0, 0.5, 0.0]

# show data from slice2
slice2Display = Show(slice2, renderView1, 'UnstructuredGridRepresentation')

# trace defaults for the display properties.
slice2Display.Set(
    Representation='Surface With Edges',
    ColorArrayName=['POINTS', 's'],
    LookupTable=sLUT,
    LineWidth=3.0,
    RenderLinesAsTubes=1,
    DisableLighting=1,
    EdgeColor=[1.0, 1.0, 1.0],
    EdgeOpacity=0.5,
    NonlinearSubdivisionLevel=2,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
slice2Display.ScaleTransferFunction.Points = [-2.5786195478251984e-38, 0.0, 0.5, 0.0, 2.357335742908888e-38, 1.0, 0.5, 0.0]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
slice2Display.OpacityTransferFunction.Points = [-2.5786195478251984e-38, 0.0, 0.5, 0.0, 2.357335742908888e-38, 1.0, 0.5, 0.0]

# show data from clipClosedSurface2
clipClosedSurface2Display = Show(clipClosedSurface2, renderView1, 'GeometryRepresentation')

# trace defaults for the display properties.
clipClosedSurface2Display.Set(
    Representation='Surface',
    ColorArrayName=[None, ''],
    Specular=0.2,
    Luminosity=50.0,
    Ambient=0.1,
    SelectNormalArray='Normals',
    ComputePointNormals=1,
    FeatureAngle=50.0,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# setup the color legend parameters for each legend in this view

# get color legend/bar for pDE_filter_mappingLUT in view renderView1
pDE_filter_mappingLUTColorBar = GetScalarBar(pDE_filter_mappingLUT, renderView1)
pDE_filter_mappingLUTColorBar.Set(
    AutoOrient=0,
    Orientation='Horizontal',
    WindowLocation='Lower Center',
    Title='Design',
    ComponentTitle='',
    TitleFontSize=32,
    LabelFontSize=32,
    ScalarBarThickness=32,
    ScalarBarLength=0.2,
    AutomaticLabelFormat=0,
    DrawTickMarks=0,
    DrawTickLabels=0,
    AddRangeLabels=0,
)

# set color bar visibility
pDE_filter_mappingLUTColorBar.Visibility = 1

# get color legend/bar for sLUT in view renderView1
sLUTColorBar = GetScalarBar(sLUT, renderView1)
sLUTColorBar.Set(
    AutoOrient=0,
    Orientation='Horizontal',
    Title='Scalar',
    ComponentTitle='',
    TitleFontSize=32,
    LabelFontSize=32,
    ScalarBarThickness=32,
    ScalarBarLength=0.2,
    DrawTickMarks=0,
    DrawTickLabels=0,
    AddRangeLabels=0,
    DrawAnnotations=0,
)

# set color bar visibility
sLUTColorBar.Visibility = 1

# show color legend
vTKmClip1Display.SetScalarBarVisibility(renderView1, True)

# show color legend
slice1Display.SetScalarBarVisibility(renderView1, True)

# show color legend
slice2Display.SetScalarBarVisibility(renderView1, True)

# ----------------------------------------------------------------
# setup color maps and opacity maps used in the visualization
# note: the Get..() functions create a new object, if needed
# ----------------------------------------------------------------

# get opacity transfer function/opacity map for 's'
sPWF = GetOpacityTransferFunction('s')
sPWF.ScalarRangeInitialized = 1

# ----------------------------------------------------------------
# setup animation scene, tracks and keyframes
# note: the Get..() functions create a new object, if needed
# ----------------------------------------------------------------

# get time animation track
timeAnimationCue1 = GetTimeTrack()

# initialize the animation scene

# get the time-keeper
timeKeeper1 = GetTimeKeeper()

# initialize the timekeeper

# initialize the animation track

# get animation scene
animationScene1 = GetAnimationScene()

# initialize the animation scene
animationScene1.Set(
    ViewModules=renderView1,
    Cues=timeAnimationCue1,
    AnimationTime=50.0,
    EndTime=200.0,
    PlayMode='Snap To TimeSteps',
)

# ----------------------------------------------------------------
# restore active source
SetActiveSource(None)
# ----------------------------------------------------------------


##--------------------------------------------
## You may need to add some code at the end of this python script depending on your usage, eg:
#
## Render all views to see them appears
# RenderAllViews()
#
## Interact with the view, usefull when running from pvpython
# Interact()
#
## Save a screenshot of the active view
# SaveScreenshot("path/to/screenshot.png")
#
## Save a screenshot of a layout (multiple splitted view)
# SaveScreenshot("path/to/screenshot.png", GetLayout())
#
## Save all "Extractors" from the pipeline browser
# SaveExtracts()
#
## Save a animation of the current active view
# SaveAnimation()
#
## Please refer to the documentation of paraview.simple
## https://www.paraview.org/paraview-docs/nightly/python/
##--------------------------------------------